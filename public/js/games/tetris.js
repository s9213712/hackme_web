'use strict';

let tetrisState = null;
let tetrisLoopTimer = null;
const TETRIS_COLS = 10;
const TETRIS_ROWS = 20;
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

function randomTetrisPiece() {
  const names = Object.keys(TETRIS_PIECES);
  const type = names[Math.floor(Math.random() * names.length)];
  return { type, shape: TETRIS_PIECES[type].map((row) => row.slice()), x: 3, y: 0 };
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
    tetrisState.lines += cleared;
    tetrisState.score += scoreTable[cleared] || cleared * 200;
  }
  return cleared;
}

function spawnTetrisPiece() {
  if (!tetrisState) return;
  tetrisState.piece = randomTetrisPiece();
  if (tetrisCollides(tetrisState.piece)) {
    finishTetrisGame();
  }
}

function clearTetrisLoop() {
  if (tetrisLoopTimer) {
    clearInterval(tetrisLoopTimer);
    tetrisLoopTimer = null;
  }
}

function startTetrisGame() {
  clearTetrisLoop();
  tetrisState = {
    grid: emptyTetrisGrid(),
    piece: null,
    score: 0,
    lines: 0,
    status: "active",
    paused: false,
    startedAt: Date.now(),
    completedAt: null,
    penaltySeconds: 0,
    scoreSubmitted: false,
    difficulty: "standard",
    puzzleId: "tetris-standard",
  };
  spawnTetrisPiece();
  renderTetrisBoard();
  ensureSoloGameTimer();
  tetrisLoopTimer = setInterval(tickTetrisGame, 650);
  updateTetrisStatus("遊戲開始。方向鍵控制，空白鍵直接落下。");
}

function tickTetrisGame() {
  if (!tetrisState || tetrisState.status !== "active" || tetrisState.paused) return;
  if (!tetrisCollides(tetrisState.piece, 0, 1)) {
    tetrisState.piece.y += 1;
  } else {
    mergeTetrisPiece();
    clearTetrisLines();
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

function toggleTetrisPause() {
  if (!tetrisState || tetrisState.status !== "active") return;
  tetrisState.paused = !tetrisState.paused;
  updateTetrisStatus(tetrisState.paused ? "已暫停。" : "繼續遊戲。");
}

function renderTetrisBoard() {
  const board = $("tetris-board");
  if (!board) return;
  if (!tetrisState) {
    board.innerHTML = '<div class="single-game-placeholder">按「開始」後開始落方塊。</div>';
    return;
  }
  const view = tetrisState.grid.map((row) => row.slice());
  const piece = tetrisState.piece;
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
    `<div class="tetris-cell ${cell ? `filled type-${sanitize(cell)}` : ""}" data-tetris-cell="${rowIndex}-${colIndex}"></div>`
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
  if (tetrisState.status === "finished") {
    status.textContent = `遊戲結束 · 分數 ${score} · 消除 ${tetrisState.lines || 0} 行 · 時間 ${time}`;
  } else {
    status.textContent = `${prefix ? `${prefix} ` : ""}${tetrisState.paused ? "暫停中 · " : ""}分數 ${score} · 消除 ${tetrisState.lines || 0} 行 · 時間 ${time}`;
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
      if (action === "tetris-left") { moveTetrisPiece(-1, 0); return true; }
      if (action === "tetris-right") { moveTetrisPiece(1, 0); return true; }
      if (action === "tetris-down") { moveTetrisPiece(0, 1); return true; }
      if (action === "tetris-rotate") { rotateTetrisPiece(); return true; }
      if (action === "tetris-drop") { hardDropTetrisPiece(); return true; }
      if (type !== "keydown" || !tetrisState || tetrisState.status !== "active") return false;
      if (["ArrowLeft", "ArrowRight", "ArrowDown", "ArrowUp", " "].includes(event.key)) {
        event.preventDefault();
      }
      if (event.key === "ArrowLeft") moveTetrisPiece(-1, 0);
      if (event.key === "ArrowRight") moveTetrisPiece(1, 0);
      if (event.key === "ArrowDown") moveTetrisPiece(0, 1);
      if (event.key === "ArrowUp") rotateTetrisPiece();
      if (event.key === " ") hardDropTetrisPiece();
      return ["ArrowLeft", "ArrowRight", "ArrowDown", "ArrowUp", " "].includes(event.key);
    },
  });
}());
