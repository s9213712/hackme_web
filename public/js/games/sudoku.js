'use strict';

const SUDOKU_PUZZLES = [
  {
    puzzle: "530070000600195000098000060800060003400803001700020006060000280000419005000080079",
    solution: "534678912672195348198342567859761423426853791713924856961537284287419635345286179",
  },
  {
    puzzle: "003020600900305001001806400008102900700000008006708200002609500800203009005010300",
    solution: "483921657967345821251876493548132976729564138136798245372689514814253769695417382",
  },
  {
    puzzle: "000260701680070090190004500820100040004602900050003028009300074040050036703018000",
    solution: "435269781682571493197834562826195347374682915951743628519326874248957136763418259",
  },
];
let sudokuState = null;

function startSudokuGame() {
  const puzzleIndex = Math.floor(Math.random() * SUDOKU_PUZZLES.length);
  const item = SUDOKU_PUZZLES[puzzleIndex];
  sudokuState = {
    puzzleId: `builtin-${puzzleIndex + 1}`,
    puzzle: item.puzzle,
    solution: item.solution,
    values: item.puzzle.split("").map((value) => value === "0" ? "" : value),
    fixed: item.puzzle.split("").map((value) => value !== "0"),
    startedAt: Date.now(),
    completedAt: null,
    penaltySeconds: 0,
    scoreSubmitted: false,
    difficulty: "standard",
  };
  renderSudokuBoard();
  ensureSoloGameTimer();
  updateSudokuStatus("計時開始。填入 1-9，完成後檢查答案。");
}

function renderSudokuBoard() {
  const board = $("sudoku-board");
  if (!board) return;
  if (!sudokuState) {
    board.innerHTML = '<div class="single-game-placeholder">按「開始」後才會出現題目並開始計時。</div>';
    return;
  }
  board.innerHTML = sudokuState.values.map((value, index) => {
    const fixed = sudokuState.fixed[index];
    const row = Math.floor(index / 9);
    const col = index % 9;
    return `
      <input class="sudoku-cell ${fixed ? "fixed" : ""}" inputmode="numeric" maxlength="1"
             aria-label="數獨第 ${row + 1} 列第 ${col + 1} 欄"
             data-sudoku-index="${index}" value="${sanitize(value || "")}" ${fixed || sudokuState.completedAt ? "readonly" : ""} />
    `;
  }).join("");
}

function updateSudokuCell(index, value) {
  if (!sudokuState || sudokuState.fixed[index] || sudokuState.completedAt) return;
  const normalized = /^[1-9]$/.test(value || "") ? value : "";
  sudokuState.values[index] = normalized;
  const input = document.querySelector(`[data-sudoku-index="${index}"]`);
  if (input && input.value !== normalized) input.value = normalized;
}

function updateSudokuStatus(prefix = "") {
  const status = $("sudoku-status");
  if (!status) return;
  if (!sudokuState) {
    status.textContent = "按開始後才會出現題目並開始計時。";
    return;
  }
  const time = formatSoloGameTime(soloElapsedMs(sudokuState));
  const penalty = Number(sudokuState.penaltySeconds || 0);
  if (sudokuState.completedAt) {
    status.textContent = `完成時間 ${time}${penalty ? `（含加時 ${penalty} 秒）` : ""}`;
    return;
  }
  status.textContent = `${prefix ? `${prefix} ` : ""}目前時間 ${time}${penalty ? ` · 加時 ${penalty} 秒` : ""}`;
}

function checkSudokuGame() {
  const status = $("sudoku-status");
  if (!sudokuState) return;
  const current = sudokuState.values.join("");
  let wrongCount = 0;
  document.querySelectorAll("[data-sudoku-index]").forEach((input) => {
    const index = Number(input.getAttribute("data-sudoku-index") || 0);
    const wrong = !!sudokuState.values[index] && sudokuState.values[index] !== sudokuState.solution[index];
    if (wrong) wrongCount += 1;
    input.classList.toggle("wrong", wrong);
  });
  if (wrongCount > 0) {
    sudokuState.penaltySeconds += 10;
    updateSudokuStatus(`發現 ${wrongCount} 格錯誤，已加時 10 秒。`);
    return;
  }
  if (sudokuState.values.some((value) => !value)) {
    updateSudokuStatus("尚未填完，目前填入的格子沒有錯。");
    return;
  }
  if (current === sudokuState.solution) {
    sudokuState.completedAt = Date.now();
    renderSudokuBoard();
    updateSudokuStatus();
    stopSoloGameTimerIfIdle();
    submitSoloGameScore("sudoku", sudokuState);
    setGameMsg(`數獨完成，成績 ${formatSoloGameTime(soloElapsedMs(sudokuState))}`, true);
  } else if (status) {
    status.textContent = "還有錯誤，請檢查紅色格子。";
  }
}

(function () {
  window.registerHackmeGameViewModule?.({
    key: "sudoku",
    panelIds: ["sudoku-game-panel"],
    ensure() {
      if (!sudokuState) {
        renderSudokuBoard();
        updateSudokuStatus();
      }
    },
    updateStatus() {
      updateSudokuStatus();
    },
    isActive() {
      return !!sudokuState && !sudokuState.completedAt;
    },
    leaderboardPath() {
      return "/games/sudoku/solo-leaderboard";
    },
    dispatch(type, event) {
      if (type === "click" && event.target?.closest?.("#sudoku-new-btn")) {
        startSudokuGame();
        return true;
      }
      if (type === "click" && event.target?.closest?.("#sudoku-check-btn")) {
        checkSudokuGame();
        return true;
      }
      const sudokuInput = type === "input" ? event.target?.closest?.("[data-sudoku-index]") : null;
      if (sudokuInput) {
        updateSudokuCell(Number(sudokuInput.dataset.sudokuIndex || 0), sudokuInput.value || "");
        return true;
      }
      return false;
    },
  });
}());
