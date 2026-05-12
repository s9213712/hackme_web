'use strict';

let minesweeperState = null;

function minesweeperConfig() {
  const difficulty = $("minesweeper-difficulty")?.value || "easy";
  if (difficulty === "hard") return { rows: 16, cols: 16, mines: 40, difficulty };
  if (difficulty === "normal") return { rows: 12, cols: 12, mines: 20, difficulty };
  return { rows: 9, cols: 9, mines: 10, difficulty: "easy" };
}

function startMinesweeperGame() {
  const config = minesweeperConfig();
  const total = config.rows * config.cols;
  minesweeperState = {
    ...config,
    status: "active",
    firstMove: true,
    startedAt: Date.now(),
    completedAt: null,
    penaltySeconds: 0,
    scoreSubmitted: false,
    puzzleId: `${config.difficulty}-${config.rows}x${config.cols}-${config.mines}`,
    cells: Array.from({ length: total }, () => ({ mine: false, revealed: false, flagged: false, count: 0 })),
  };
  renderMinesweeperBoard();
  ensureSoloGameTimer();
  updateMinesweeperStatus();
}

function placeMinesweeperMines(safeIndex) {
  const state = minesweeperState;
  if (!state) return;
  const blocked = new Set([safeIndex, ...minesweeperNeighbors(safeIndex)]);
  const choices = state.cells.map((_cell, index) => index).filter((index) => !blocked.has(index));
  for (let placed = 0; placed < state.mines && choices.length; placed += 1) {
    const pick = Math.floor(Math.random() * choices.length);
    const index = choices.splice(pick, 1)[0];
    state.cells[index].mine = true;
  }
  state.cells.forEach((cell, index) => {
    cell.count = cell.mine ? 0 : minesweeperNeighbors(index).filter((neighbor) => state.cells[neighbor].mine).length;
  });
  state.firstMove = false;
}

function minesweeperNeighbors(index) {
  const state = minesweeperState;
  if (!state) return [];
  const row = Math.floor(index / state.cols);
  const col = index % state.cols;
  const neighbors = [];
  for (let dr = -1; dr <= 1; dr += 1) {
    for (let dc = -1; dc <= 1; dc += 1) {
      if (dr === 0 && dc === 0) continue;
      const nr = row + dr;
      const nc = col + dc;
      if (nr >= 0 && nr < state.rows && nc >= 0 && nc < state.cols) {
        neighbors.push(nr * state.cols + nc);
      }
    }
  }
  return neighbors;
}

function revealMinesweeperCell(index) {
  const state = minesweeperState;
  index = Number(index);
  if (!state || state.status === "lost" || state.status === "won") return;
  if (state.firstMove) placeMinesweeperMines(index);
  const cell = state.cells[index];
  if (!cell || cell.flagged || cell.revealed) return;
  cell.revealed = true;
  if (cell.mine) {
    state.status = "lost";
    state.completedAt = Date.now();
    state.cells.forEach((item) => { if (item.mine) item.revealed = true; });
    renderMinesweeperBoard();
    updateMinesweeperStatus();
    stopSoloGameTimerIfIdle();
    return;
  }
  if (cell.count === 0) {
    minesweeperNeighbors(index).forEach((neighbor) => {
      if (!state.cells[neighbor].revealed) revealMinesweeperCell(neighbor);
    });
  }
  if (state.cells.every((item) => item.mine || item.revealed)) {
    state.status = "won";
    state.completedAt = Date.now();
    state.cells.forEach((item) => { if (item.mine) item.flagged = true; });
    submitSoloGameScore("minesweeper", state);
    setGameMsg(`踩地雷完成，成績 ${formatSoloGameTime(soloElapsedMs(state))}`, true);
    stopSoloGameTimerIfIdle();
  }
  renderMinesweeperBoard();
  updateMinesweeperStatus();
}

function toggleMinesweeperFlag(index) {
  const state = minesweeperState;
  index = Number(index);
  if (!state || state.status === "lost" || state.status === "won") return;
  const cell = state.cells[index];
  if (!cell || cell.revealed) return;
  cell.flagged = !cell.flagged;
  renderMinesweeperBoard();
  updateMinesweeperStatus();
}

function renderMinesweeperBoard() {
  const board = $("minesweeper-board");
  const state = minesweeperState;
  if (!board) return;
  if (!state) {
    board.innerHTML = '<div class="single-game-placeholder">按「開始」後才會出現盤面並開始計時。</div>';
    return;
  }
  board.style.setProperty("--mine-cols", String(state.cols));
  board.innerHTML = state.cells.map((cell, index) => {
    const label = cell.revealed ? (cell.mine ? "*" : (cell.count || "")) : (cell.flagged ? "⚑" : "");
    const tone = cell.revealed && cell.mine ? "mine" : cell.revealed ? "revealed" : cell.flagged ? "flagged" : "";
    return `<button class="mine-cell ${tone}" type="button" data-mine-index="${index}">${sanitize(String(label))}</button>`;
  }).join("");
}

function updateMinesweeperStatus() {
  const status = $("minesweeper-status");
  if (!status) return;
  if (!minesweeperState) {
    status.textContent = "按開始後才會出現盤面並開始計時。";
    return;
  }
  const flagged = minesweeperState.cells.filter((cell) => cell.flagged).length;
  const elapsed = formatSoloGameTime(soloElapsedMs(minesweeperState));
  if (minesweeperState.status === "won") {
    status.textContent = `完成，所有安全格都已翻開。成績 ${elapsed}`;
  } else if (minesweeperState.status === "lost") {
    status.textContent = `踩到地雷，請重開一局。本局時間 ${elapsed}`;
  } else {
    status.textContent = `時間 ${elapsed} · 地雷 ${minesweeperState.mines} · 已插旗 ${flagged} · 左鍵翻格，右鍵插旗。`;
  }
}

(function () {
  window.registerHackmeGameViewModule?.({
    key: "minesweeper",
    panelIds: ["minesweeper-game-panel"],
    ensure() {
      if (!minesweeperState) {
        renderMinesweeperBoard();
        updateMinesweeperStatus();
      }
    },
    updateStatus() {
      updateMinesweeperStatus();
    },
    isActive() {
      return !!minesweeperState && minesweeperState.status === "active";
    },
    leaderboardPath() {
      return `/games/minesweeper/solo-leaderboard?difficulty=${encodeURIComponent(minesweeperConfig().difficulty)}`;
    },
    dispatch(type, event) {
      if (type === "click" && event.target?.closest?.("#minesweeper-new-btn")) {
        startMinesweeperGame();
        return true;
      }
      const mineBtn = event.target?.closest?.("[data-mine-index]");
      if (type === "click" && mineBtn) {
        revealMinesweeperCell(mineBtn.dataset.mineIndex);
        return true;
      }
      if (type === "contextmenu" && mineBtn) {
        event.preventDefault();
        toggleMinesweeperFlag(mineBtn.dataset.mineIndex);
        return true;
      }
      if (type === "change" && event.target?.closest?.("#minesweeper-difficulty")) {
        loadSelectedGameLeaderboard().catch((err) => setGameMsg(err.message || "排行榜讀取失敗", false));
        return true;
      }
      return false;
    },
  });
}());
