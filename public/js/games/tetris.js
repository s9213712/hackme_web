'use strict';

let tetrisState = null;
let tetrisLoopTimer = null;
let tetrisInputTimer = null;
let tetrisHeldTouchAction = "";
let tetrisSuppressTouchClick = false;
const TETRIS_COLS = 10;
const TETRIS_ROWS = 20;
const TETRIS_SIDE_REPEAT_MS = 82;
const TETRIS_SOFT_DROP_MS = 46;
const TETRIS_ASSET_SOURCES = Object.freeze({
  puzzlePack: {
    name: "Kenney Puzzle Pack 2",
    url: "https://kenney.nl/assets/puzzle-pack-2",
    license: "Creative Commons CC0",
    usage: "bundled PNG tile skins applied through CSS with color fallback",
  },
});
const TETRIS_PIECES = {
  I: [[1, 1, 1, 1]],
  O: [[1, 1], [1, 1]],
  T: [[0, 1, 0], [1, 1, 1]],
  S: [[0, 1, 1], [1, 1, 0]],
  Z: [[1, 1, 0], [0, 1, 1]],
  J: [[1, 0, 0], [1, 1, 1]],
  L: [[0, 0, 1], [1, 1, 1]],
};

function emptyTetrisGrid() {
  return Array.from({ length: TETRIS_ROWS }, () => Array(TETRIS_COLS).fill(""));
}

function tetrisRandom() {
  return typeof tetrisState?.rng === "function" ? tetrisState.rng() : Math.random();
}

function createTetrisPiece(type) {
  const pieceType = TETRIS_PIECES[type] ? type : "T";
  const shape = TETRIS_PIECES[pieceType].map((row) => row.slice());
  return { type: pieceType, shape, x: Math.floor((TETRIS_COLS - shape[0].length) / 2), y: 0 };
}

function refillTetrisBag() {
  if (!tetrisState) return;
  const names = Object.keys(TETRIS_PIECES);
  const bag = names.slice();
  for (let i = bag.length - 1; i > 0; i -= 1) {
    const j = Math.floor(tetrisRandom() * (i + 1));
    [bag[i], bag[j]] = [bag[j], bag[i]];
  }
  tetrisState.bag = bag;
}

function drawTetrisPieceType() {
  if (!tetrisState) {
    const names = Object.keys(TETRIS_PIECES);
    return names[Math.floor(Math.random() * names.length)];
  }
  if (!tetrisState.bag?.length) refillTetrisBag();
  return tetrisState.bag.shift() || "T";
}

function randomTetrisPiece() {
  return createTetrisPiece(drawTetrisPieceType());
}

function recordTetrisAchievement(id, label, detail = "") {
  const result = window.recordHackmeGameAchievement?.("tetris", id, label, detail);
  if (result?.unlocked && typeof setGameMsg === "function") setGameMsg(`成就解鎖：${result.label}`, true);
  return result || { unlocked: false };
}

function rotateTetrisShape(shape) {
  return shape[0].map((_cell, col) => shape.map((row) => row[col]).reverse());
}

function tetrisCollides(piece, offsetX = 0, offsetY = 0, shape = null) {
  if (!tetrisState || !piece) return true;
  const matrix = shape || piece.shape;
  for (let row = 0; row < matrix.length; row += 1) {
    for (let col = 0; col < matrix[row].length; col += 1) {
      if (!matrix[row][col]) continue;
      const x = piece.x + col + offsetX;
      const y = piece.y + row + offsetY;
      if (x < 0 || x >= TETRIS_COLS || y >= TETRIS_ROWS) return true;
      if (y >= 0 && tetrisState.grid[y][x]) return true;
    }
  }
  return false;
}

function mergeTetrisPiece() {
  const piece = tetrisState?.piece;
  if (!tetrisState || !piece) return;
  piece.shape.forEach((row, rowIndex) => {
    row.forEach((cell, colIndex) => {
      if (!cell) return;
      const y = piece.y + rowIndex;
      const x = piece.x + colIndex;
      if (y >= 0 && y < TETRIS_ROWS && x >= 0 && x < TETRIS_COLS) {
        tetrisState.grid[y][x] = piece.type;
      }
    });
  });
}

function clearTetrisLines() {
  if (!tetrisState) return 0;
  const kept = tetrisState.grid.filter((row) => row.some((cell) => !cell));
  const cleared = TETRIS_ROWS - kept.length;
  while (kept.length < TETRIS_ROWS) kept.unshift(Array(TETRIS_COLS).fill(""));
  tetrisState.grid = kept;
  if (cleared) {
    const scoreTable = [0, 100, 300, 500, 800];
    tetrisState.combo = Number(tetrisState.combo || 0) + 1;
    tetrisState.maxCombo = Math.max(Number(tetrisState.maxCombo || 0), tetrisState.combo);
    const comboBonus = Math.max(0, tetrisState.combo - 1) * cleared * 50;
    const b2bBonus = cleared >= 4 && tetrisState.backToBack ? 350 : 0;
    tetrisState.lines += cleared;
    tetrisState.score += (scoreTable[cleared] || cleared * 200) + comboBonus + b2bBonus;
    if (cleared >= 4) {
      recordTetrisAchievement("tetris-clear", "四行消除", "一次消除四行。");
      if (tetrisState.backToBack) recordTetrisAchievement("back-to-back", "Back-to-Back", "連續兩次四行消除。");
      tetrisState.backToBack = true;
    } else {
      tetrisState.backToBack = false;
    }
    if (tetrisState.combo >= 3) recordTetrisAchievement("combo-chain", "連續消除", "連續 3 次落子都有消行。");
  }
  return cleared;
}

function addTetrisGarbageLine() {
  if (!tetrisState) return;
  const hole = Math.floor(tetrisRandom() * TETRIS_COLS);
  tetrisState.grid.shift();
  tetrisState.grid.push(Array.from({ length: TETRIS_COLS }, (_cell, index) => index === hole ? "" : "G"));
}

function spawnTetrisPiece() {
  if (!tetrisState) return;
  tetrisState.piece = tetrisState.nextPiece || randomTetrisPiece();
  tetrisState.nextPiece = randomTetrisPiece();
  tetrisState.holdUsed = false;
  if (tetrisCollides(tetrisState.piece)) {
    finishTetrisGame();
  }
}

function clearTetrisLoop() {
  if (tetrisLoopTimer) {
    clearInterval(tetrisLoopTimer);
    tetrisLoopTimer = null;
  }
  if (tetrisInputTimer) {
    clearInterval(tetrisInputTimer);
    tetrisInputTimer = null;
  }
  tetrisHeldTouchAction = "";
}

function startTetrisGame() {
  clearTetrisLoop();
  const dailyChallenge = window.hackmeGameDailyChallenge?.("tetris") || null;
  tetrisState = {
    grid: emptyTetrisGrid(),
    piece: null,
    nextPiece: null,
    heldPiece: null,
    holdUsed: false,
    bag: [],
    combo: 0,
    maxCombo: 0,
    backToBack: false,
    garbageCounter: 0,
    score: 0,
    lines: 0,
    status: "active",
    paused: false,
    startedAt: Date.now(),
    completedAt: null,
    penaltySeconds: 0,
    scoreSubmitted: false,
    difficulty: dailyChallenge?.difficulty || "standard",
    puzzleId: dailyChallenge?.key || "tetris-standard",
    dailyChallenge,
    rng: dailyChallenge?.seed ? window.createHackmeGameSeededRandom?.(dailyChallenge.seed) : null,
    keys: {},
    lastMoveAt: 0,
    lastSoftDropAt: 0,
  };
  tetrisState.nextPiece = randomTetrisPiece();
  spawnTetrisPiece();
  renderTetrisBoard();
  ensureSoloGameTimer();
  tetrisLoopTimer = setInterval(tickTetrisGame, 650);
  tetrisInputTimer = setInterval(tickTetrisInput, 35);
  updateTetrisStatus(`${dailyChallenge?.label || "遊戲開始"}。方向鍵控制，C 可 Hold，空白鍵直接落下。`);
}

function tickTetrisInput(now = performance.now()) {
  if (!tetrisState || tetrisState.status !== "active" || tetrisState.paused) return;
  const left = Boolean(tetrisState.keys.ArrowLeft);
  const right = Boolean(tetrisState.keys.ArrowRight);
  if (left !== right) {
    if (!tetrisState.lastMoveAt || now - tetrisState.lastMoveAt >= TETRIS_SIDE_REPEAT_MS) {
      moveTetrisPiece(left ? -1 : 1, 0);
      tetrisState.lastMoveAt = now;
    }
  } else {
    tetrisState.lastMoveAt = 0;
  }
  if (tetrisState.keys.ArrowDown) {
    if (!tetrisState.lastSoftDropAt || now - tetrisState.lastSoftDropAt >= TETRIS_SOFT_DROP_MS) {
      moveTetrisPiece(0, 1);
      tetrisState.lastSoftDropAt = now;
    }
  } else {
    tetrisState.lastSoftDropAt = 0;
  }
}

function tickTetrisGame() {
  if (!tetrisState || tetrisState.status !== "active" || tetrisState.paused) return;
  if (!tetrisCollides(tetrisState.piece, 0, 1)) {
    tetrisState.piece.y += 1;
  } else {
    mergeTetrisPiece();
    const cleared = clearTetrisLines();
    if (!cleared) tetrisState.combo = 0;
    tetrisState.garbageCounter += 1;
    if (tetrisState.dailyChallenge?.modifier === "survival" && tetrisState.garbageCounter % 9 === 0) {
      addTetrisGarbageLine();
      updateTetrisStatus("垃圾行上升。");
    }
    spawnTetrisPiece();
  }
  renderTetrisBoard();
  updateTetrisStatus();
}

function finishTetrisGame() {
  if (!tetrisState || tetrisState.status === "finished") return;
  tetrisState.status = "finished";
  tetrisState.completedAt = Date.now();
  clearTetrisLoop();
  renderTetrisBoard();
  updateTetrisStatus();
  stopSoloGameTimerIfIdle();
  if (Number(tetrisState.score || 0) > 0) {
    recordTetrisAchievement("score-posted", "方塊上榜", "完成一局並送出分數。");
    submitSoloGameScore("tetris", tetrisState);
  }
  setGameMsg(`俄羅斯方塊結束，分數 ${Number(tetrisState.score || 0).toLocaleString()}`, true);
}

function moveTetrisPiece(dx, dy) {
  if (!tetrisState || tetrisState.status !== "active" || tetrisState.paused) return;
  if (!tetrisCollides(tetrisState.piece, dx, dy)) {
    tetrisState.piece.x += dx;
    tetrisState.piece.y += dy;
    tetrisState.score += dy > 0 ? 1 : 0;
    renderTetrisBoard();
    updateTetrisStatus();
  }
}

function rotateTetrisPiece() {
  if (!tetrisState || tetrisState.status !== "active" || tetrisState.paused) return;
  const rotated = rotateTetrisShape(tetrisState.piece.shape);
  if (!tetrisCollides(tetrisState.piece, 0, 0, rotated)) {
    tetrisState.piece.shape = rotated;
  } else if (!tetrisCollides(tetrisState.piece, -1, 0, rotated)) {
    tetrisState.piece.x -= 1;
    tetrisState.piece.shape = rotated;
  } else if (!tetrisCollides(tetrisState.piece, 1, 0, rotated)) {
    tetrisState.piece.x += 1;
    tetrisState.piece.shape = rotated;
  }
  renderTetrisBoard();
}

function hardDropTetrisPiece() {
  if (!tetrisState || tetrisState.status !== "active" || tetrisState.paused) return;
  let moved = 0;
  while (!tetrisCollides(tetrisState.piece, 0, 1)) {
    tetrisState.piece.y += 1;
    moved += 1;
  }
  tetrisState.score += moved * 2;
  tickTetrisGame();
}

function holdTetrisPiece() {
  if (!tetrisState || tetrisState.status !== "active" || tetrisState.paused || tetrisState.holdUsed || !tetrisState.piece) return;
  const currentType = tetrisState.piece.type;
  if (tetrisState.heldPiece) {
    const swapType = tetrisState.heldPiece.type;
    tetrisState.heldPiece = createTetrisPiece(currentType);
    tetrisState.piece = createTetrisPiece(swapType);
  } else {
    tetrisState.heldPiece = createTetrisPiece(currentType);
    spawnTetrisPiece();
  }
  tetrisState.holdUsed = true;
  recordTetrisAchievement("hold-used", "戰術 Hold", "使用 Hold 保留一塊方塊。");
  if (tetrisCollides(tetrisState.piece)) finishTetrisGame();
  renderTetrisBoard();
  updateTetrisStatus("已 Hold。");
}

function setTetrisHeldKey(key, pressed) {
  if (!tetrisState?.keys) return;
  tetrisState.keys[key] = pressed;
  if (!pressed) return;
  if (key === "ArrowLeft") moveTetrisPiece(-1, 0);
  if (key === "ArrowRight") moveTetrisPiece(1, 0);
  if (key === "ArrowDown") moveTetrisPiece(0, 1);
}

function setTetrisTouchAction(action, pressed) {
  if (!tetrisState || tetrisState.status !== "active") return;
  if (action === "tetris-left") setTetrisHeldKey("ArrowLeft", pressed);
  if (action === "tetris-right") setTetrisHeldKey("ArrowRight", pressed);
  if (action === "tetris-down") setTetrisHeldKey("ArrowDown", pressed);
}

function toggleTetrisPause() {
  if (!tetrisState || tetrisState.status !== "active") return;
  tetrisState.paused = !tetrisState.paused;
  updateTetrisStatus(tetrisState.paused ? "已暫停。" : "繼續遊戲。");
}

function suspendTetrisGame() {
  if (!tetrisState || tetrisState.status !== "active") return;
  tetrisState.paused = true;
  tetrisState.keys = {};
  tetrisHeldTouchAction = "";
  updateTetrisStatus("已暫停；切回本遊戲後可按「暫停」繼續。");
}

function tetrisGhostPiece(piece) {
  if (!piece) return null;
  const ghost = {
    type: piece.type,
    shape: piece.shape.map((row) => row.slice()),
    x: piece.x,
    y: piece.y,
  };
  while (!tetrisCollides(ghost, 0, 1)) ghost.y += 1;
  return ghost;
}

function tetrisPieceLabel(piece) {
  return piece?.type || "空";
}

function renderTetrisBoard() {
  const board = $("tetris-board");
  if (!board) return;
  board.dataset.assetTheme = "kenney-puzzle-pack";
  if (!tetrisState) {
    board.innerHTML = '<div class="single-game-placeholder">按「開始」後開始落方塊。</div>';
    return;
  }
  const view = tetrisState.grid.map((row) => row.slice());
  const piece = tetrisState.piece;
  const ghost = tetrisState.status === "active" ? tetrisGhostPiece(piece) : null;
  if (ghost) {
    ghost.shape.forEach((row, rowIndex) => {
      row.forEach((cell, colIndex) => {
        if (!cell) return;
        const y = ghost.y + rowIndex;
        const x = ghost.x + colIndex;
        if (y >= 0 && y < TETRIS_ROWS && x >= 0 && x < TETRIS_COLS && !view[y][x]) view[y][x] = "ghost";
      });
    });
  }
  if (piece && tetrisState.status === "active") {
    piece.shape.forEach((row, rowIndex) => {
      row.forEach((cell, colIndex) => {
        if (!cell) return;
        const y = piece.y + rowIndex;
        const x = piece.x + colIndex;
        if (y >= 0 && y < TETRIS_ROWS && x >= 0 && x < TETRIS_COLS) view[y][x] = piece.type;
      });
    });
  }
  const cells = view.flatMap((row, rowIndex) => row.map((cell, colIndex) => (
    `<div class="tetris-cell ${cell === "ghost" ? "ghost" : cell ? `filled type-${sanitize(cell)}` : ""}" data-tetris-cell="${rowIndex}-${colIndex}"></div>`
  ))).join("");
  const overlay = tetrisState.status === "finished"
    ? `<div class="single-game-over-overlay">GAME OVER<br><small>分數 ${Number(tetrisState.score || 0).toLocaleString()} · 消除 ${tetrisState.lines || 0} 行</small></div>`
    : "";
  board.innerHTML = cells + overlay;
}

function updateTetrisStatus(prefix = "") {
  const status = $("tetris-status");
  if (!status) return;
  if (!tetrisState) {
    status.textContent = "按開始後開始落方塊，最高分列入排行榜。";
    return;
  }
  const score = Number(tetrisState.score || 0).toLocaleString();
  const time = formatSoloGameTime(soloElapsedMs(tetrisState));
  const preview = `下一塊 ${tetrisPieceLabel(tetrisState.nextPiece)} · Hold ${tetrisPieceLabel(tetrisState.heldPiece)}${tetrisState.combo > 1 ? ` · Combo x${tetrisState.combo}` : ""}${tetrisState.backToBack ? " · B2B" : ""}`;
  if (tetrisState.status === "finished") {
    status.textContent = `遊戲結束 · 分數 ${score} · 消除 ${tetrisState.lines || 0} 行 · 時間 ${time} · ${preview}`;
  } else {
    status.textContent = `${prefix ? `${prefix} ` : ""}${tetrisState.paused ? "暫停中 · " : ""}分數 ${score} · 消除 ${tetrisState.lines || 0} 行 · 時間 ${time} · ${preview}`;
  }
}

(function () {
  window.registerHackmeGameViewModule?.({
    key: "tetris",
    panelIds: ["tetris-game-panel"],
    ensure() {
      if (!tetrisState) {
        renderTetrisBoard();
        updateTetrisStatus();
      }
    },
    updateStatus() {
      updateTetrisStatus();
    },
    isActive() {
      return !!tetrisState && tetrisState.status === "active";
    },
    suspend() {
      suspendTetrisGame();
    },
    leaderboardPath() {
      return "/games/tetris/solo-leaderboard";
    },
    dispatch(type, event) {
      if (type === "click" && event.target?.closest?.("#tetris-new-btn")) {
        startTetrisGame();
        return true;
      }
      if (type === "click" && event.target?.closest?.("#tetris-pause-btn")) {
        toggleTetrisPause();
        return true;
      }
      const touchBtn = type === "click" ? event.target?.closest?.("[data-game-touch]") : null;
      const action = touchBtn?.dataset.gameTouch || "";
      if (touchBtn && tetrisSuppressTouchClick) {
        tetrisSuppressTouchClick = false;
        return true;
      }
      if (action === "tetris-left") { moveTetrisPiece(-1, 0); return true; }
      if (action === "tetris-right") { moveTetrisPiece(1, 0); return true; }
      if (action === "tetris-down") { moveTetrisPiece(0, 1); return true; }
      if (action === "tetris-rotate") { rotateTetrisPiece(); return true; }
      if (action === "tetris-drop") { hardDropTetrisPiece(); return true; }
      if (action === "tetris-hold") { holdTetrisPiece(); return true; }
      if (!["keydown", "keyup"].includes(type) || !tetrisState || tetrisState.status !== "active") return false;
      if (["ArrowLeft", "ArrowRight", "ArrowDown", "ArrowUp", " ", "c", "C"].includes(event.key)) {
        event.preventDefault();
      }
      const pressed = type === "keydown";
      if (event.key === "ArrowLeft" || event.key === "ArrowRight" || event.key === "ArrowDown") {
        if (pressed && !tetrisState.keys[event.key]) setTetrisHeldKey(event.key, true);
        else tetrisState.keys[event.key] = pressed;
      }
      if (pressed && event.key === "ArrowUp") rotateTetrisPiece();
      if (pressed && event.key === " ") hardDropTetrisPiece();
      if (pressed && (event.key === "c" || event.key === "C")) holdTetrisPiece();
      return ["ArrowLeft", "ArrowRight", "ArrowDown", "ArrowUp", " ", "c", "C"].includes(event.key);
    },
  });

  document.addEventListener("pointerdown", (event) => {
    const touchBtn = event.target?.closest?.("#tetris-game-panel [data-game-touch]");
    if (!touchBtn || !tetrisState || tetrisState.status !== "active") return;
    const action = touchBtn.dataset.gameTouch || "";
    event.preventDefault();
    tetrisSuppressTouchClick = true;
    window.setTimeout(() => { tetrisSuppressTouchClick = false; }, 220);
    tetrisHeldTouchAction = action;
    if (action === "tetris-rotate") rotateTetrisPiece();
    else if (action === "tetris-drop") hardDropTetrisPiece();
    else if (action === "tetris-hold") holdTetrisPiece();
    else setTetrisTouchAction(action, true);
  });

  const releaseTetrisTouch = () => {
    if (!tetrisHeldTouchAction) return;
    setTetrisTouchAction(tetrisHeldTouchAction, false);
    tetrisHeldTouchAction = "";
  };
  document.addEventListener("pointerup", releaseTetrisTouch);
  document.addEventListener("pointercancel", releaseTetrisTouch);
}());
