'use strict';

let gameSelectedMatchId = null;
let gameSelectedSquare = null;
let gameSelectedKey = "chess";
let chessMoveInFlight = false;
let gameState = { matches: [], invites: [], leaderboard: [] };
let soloGameTimer = null;
const CHESS_PIECES = {
  K: "♔", Q: "♕", R: "♖", B: "♗", N: "♘", P: "♙",
  k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟",
};
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
let minesweeperState = null;
let oneA2BState = null;
let tetrisState = null;
let tetrisLoopTimer = null;
let spaceShooterState = null;
let spaceShooterLoopTimer = null;
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

function setOneA2BNotice(text, ms = 3500) {
  if (!oneA2BState) return;
  oneA2BState.notice = text || "";
  oneA2BState.noticeUntil = text ? Date.now() + ms : 0;
}

function formatSoloGameTime(ms) {
  const totalMs = Math.max(0, Number(ms || 0));
  const totalSeconds = Math.floor(totalMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const tenths = Math.floor((totalMs % 1000) / 100);
  return `${minutes}:${String(seconds).padStart(2, "0")}.${tenths}`;
}

function soloRawElapsedMs(state) {
  if (!state?.startedAt) return 0;
  const end = state.completedAt || Date.now();
  return Math.max(1, Math.floor(end - state.startedAt));
}

function soloElapsedMs(state) {
  return soloRawElapsedMs(state) + Number(state?.penaltySeconds || 0) * 1000;
}

function ensureSoloGameTimer() {
  if (soloGameTimer) return;
  soloGameTimer = setInterval(() => {
    if (gameSelectedKey === "sudoku") updateSudokuStatus();
    if (gameSelectedKey === "minesweeper") updateMinesweeperStatus();
    if (gameSelectedKey === "1a2b") updateOneA2BStatus();
    if (gameSelectedKey === "tetris") updateTetrisStatus();
    if (gameSelectedKey === "space_shooter") updateSpaceShooterStatus();
  }, 250);
}

function stopSoloGameTimerIfIdle() {
  const sudokuActive = sudokuState && !sudokuState.completedAt;
  const minesActive = minesweeperState && minesweeperState.status === "active";
  const oneA2BActive = oneA2BState && !oneA2BState.completedAt;
  const tetrisActive = tetrisState && tetrisState.status === "active";
  const shooterActive = spaceShooterState && spaceShooterState.status === "active";
  if (!sudokuActive && !minesActive && !oneA2BActive && !tetrisActive && !shooterActive && soloGameTimer) {
    clearInterval(soloGameTimer);
    soloGameTimer = null;
  }
}

function setGameMsg(text, ok) {
  const el = $("game-msg");
  if (!el) return;
  el.textContent = text || "";
  el.className = text ? "msg show " + (ok ? "ok" : "err") : "msg";
}

function gameIcon(key) {
  if (key === "sudoku") return "9";
  if (key === "minesweeper") return "!";
  if (key === "1a2b") return "A";
  if (key === "tetris") return "▦";
  if (key === "space_shooter") return "▲";
  return "♟";
}

function gameSubtitle(game) {
  if (game.key === "sudoku") return "單人邏輯解題";
  if (game.key === "minesweeper") return "單人推理挑戰";
  if (game.key === "1a2b") return "單人猜數字";
  if (game.key === "tetris") return "高分消除挑戰";
  if (game.key === "space_shooter") return "高分射擊挑戰";
  return game.supports_computer ? "玩家對戰 / 電腦練習" : "玩家對戰";
}

function switchGameView(key) {
  setGameMsg("", true);
  gameSelectedKey = key || "chess";
  const isChess = gameSelectedKey === "chess";
  const chessLobby = $("chess-lobby-panel");
  const chessPanel = $("chess-game-panel");
  const sudokuPanel = $("sudoku-game-panel");
  const minesPanel = $("minesweeper-game-panel");
  const oneA2BPanel = $("onea2b-game-panel");
  const tetrisPanel = $("tetris-game-panel");
  const shooterPanel = $("space-shooter-game-panel");
  if (chessLobby) chessLobby.style.display = isChess ? "" : "none";
  if (chessPanel) chessPanel.style.display = isChess ? "" : "none";
  if (sudokuPanel) sudokuPanel.style.display = gameSelectedKey === "sudoku" ? "" : "none";
  if (minesPanel) minesPanel.style.display = gameSelectedKey === "minesweeper" ? "" : "none";
  if (oneA2BPanel) oneA2BPanel.style.display = gameSelectedKey === "1a2b" ? "" : "none";
  if (tetrisPanel) tetrisPanel.style.display = gameSelectedKey === "tetris" ? "" : "none";
  if (shooterPanel) shooterPanel.style.display = gameSelectedKey === "space_shooter" ? "" : "none";
  document.querySelectorAll("[data-game-key]").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-game-key") === gameSelectedKey);
  });
  if (gameSelectedKey === "sudoku" && !sudokuState) {
    renderSudokuBoard();
    updateSudokuStatus();
  }
  if (gameSelectedKey === "minesweeper" && !minesweeperState) {
    renderMinesweeperBoard();
    updateMinesweeperStatus();
  }
  if (gameSelectedKey === "1a2b" && !oneA2BState) {
    renderOneA2BBoard();
    updateOneA2BStatus();
  }
  if (gameSelectedKey === "tetris" && !tetrisState) {
    renderTetrisBoard();
    updateTetrisStatus();
  }
  if (gameSelectedKey === "space_shooter" && !spaceShooterState) {
    renderSpaceShooterBoard();
    updateSpaceShooterStatus();
  }
  loadSelectedGameLeaderboard().catch((err) => setGameMsg(err.message || "排行榜讀取失敗", false));
}

function gameRequestNeedsFreshCsrf(json, res) {
  return res.status === 403 && String(json?.msg || "").toUpperCase().includes("CSRF");
}

async function gameRequest(path, { method = "GET", body = null } = {}) {
  const upperMethod = String(method || "GET").toUpperCase();
  const mutates = upperMethod !== "GET";
  const buildOptions = async () => {
    const csrf = await fetchCsrfToken({ force: mutates });
    const headers = { "X-CSRF-Token": csrf || "" };
    if (mutates) headers["Content-Type"] = "application/json";
    return {
      method: upperMethod,
      credentials: "same-origin",
      cache: "no-store",
      headers,
      body: body ? JSON.stringify(body) : undefined,
    };
  };

  let res = await apiFetch(API + path, await buildOptions());
  let json = await res.json().catch(() => ({}));
  if (gameRequestNeedsFreshCsrf(json, res)) {
    await fetchCsrfToken({ force: true });
    res = await apiFetch(API + path, await buildOptions());
    json = await res.json().catch(() => ({}));
  }
  if (!res.ok || !json.ok) {
    throw new Error(json.msg || `HTTP ${res.status}`);
  }
  if (mutates && typeof _csrfToken !== "undefined") {
    setCsrfToken(null);
  }
  return json;
}

function renderGameCatalog(games) {
  const wrap = $("game-catalog-list");
  if (!wrap) return;
  const rows = Array.isArray(games) ? games : [];
  wrap.innerHTML = rows.map((game) => `
    <button class="game-catalog-item ${game.key === gameSelectedKey ? "active" : ""}" type="button" data-game-key="${sanitize(game.key || "chess")}">
      <span class="game-catalog-icon">${sanitize(gameIcon(game.key))}</span>
      <span><strong>${sanitize(game.title || "西洋棋")}</strong><small>${sanitize(gameSubtitle(game))}</small></span>
    </button>
  `).join("") || "<p style=\"color:var(--muted);\">尚未開放遊戲</p>";
  if (!rows.some((game) => game.key === gameSelectedKey)) gameSelectedKey = "chess";
  switchGameView(gameSelectedKey);
}

function renderGameUsers(users) {
  const select = $("game-invite-user");
  if (!select) return;
  const rows = Array.isArray(users) ? users : [];
  if (!rows.length) {
    select.innerHTML = '<option value="">目前沒有可邀請玩家</option>';
    return;
  }
  select.innerHTML = '<option value="">選擇玩家</option>' + rows.map((user) => (
    `<option value="${sanitize(user.username || "")}">${sanitize(user.username || "")} · ${sanitize(user.role || "user")}</option>`
  )).join("");
}

function renderGameInvites(invites) {
  const wrap = $("game-invite-list");
  if (!wrap) return;
  const rows = Array.isArray(invites) ? invites : [];
  if (!rows.length) {
    wrap.innerHTML = "<p style=\"color:var(--muted);\">目前沒有邀請</p>";
    return;
  }
  wrap.innerHTML = rows.map((invite) => {
    const incoming = invite.opponent_username === currentUser;
    const title = incoming ? `${invite.inviter_username} 邀請你對戰` : `邀請 ${invite.opponent_username}`;
    const actions = invite.status === "pending" && incoming
      ? `<button class="btn game-mini-btn btn-primary" type="button" data-game-invite="${invite.id}" data-game-invite-action="accept">接受</button>
         <button class="btn game-mini-btn" type="button" data-game-invite="${invite.id}" data-game-invite-action="reject">拒絕</button>`
      : invite.status === "pending"
        ? `<button class="btn game-mini-btn" type="button" data-game-invite="${invite.id}" data-game-invite-action="cancel">取消</button>`
        : "";
    return `
      <div class="drive-file-row game-list-row">
        <div><strong>${sanitize(title)}</strong><small>${sanitize(invite.status)} · ${sanitize(formatChatTime(invite.created_at))}</small></div>
        <div class="drive-file-actions">${actions}</div>
      </div>
    `;
  }).join("");
}

function gameMatchLabel(match) {
  const side = match.my_side === "black" ? "黑方" : "白方";
  const opponentName = match.my_side === "black" ? match.white_username : match.black_username;
  const difficulty = match.mode === "computer" ? ` · ${gameDifficultyLabel(match.computer_difficulty)}` : "";
  return `${side} vs ${opponentName || "電腦"}${difficulty}`;
}

function gameDifficultyLabel(difficulty) {
  if (difficulty === "experiment") return "實驗";
  if (difficulty === "hard") return "困難";
  return "普通";
}

function renderGameMatches(matches) {
  const wrap = $("game-match-list");
  if (!wrap) return;
  const rows = Array.isArray(matches) ? matches : [];
  if (!gameSelectedMatchId && rows.length) {
    gameSelectedMatchId = rows[0].id;
  }
  if (!rows.length) {
    wrap.innerHTML = "<p style=\"color:var(--muted);\">還沒有棋局</p>";
    renderChessBoard(null);
    return;
  }
  wrap.innerHTML = rows.map((match) => {
    const canDelete = match.status !== "active";
    return `
      <div class="game-match-item ${match.id === gameSelectedMatchId ? "active" : ""}">
        <button class="game-match-row ${match.id === gameSelectedMatchId ? "active" : ""}" type="button" data-game-match-id="${match.id}">
          <span><strong>${sanitize(gameMatchLabel(match))}</strong><small>${sanitize(match.status)} · ${sanitize(match.current_turn === "white" ? "白方走" : "黑方走")}</small></span>
          <span>${match.mode === "computer" ? "練習" : "對戰"}</span>
        </button>
        ${canDelete ? `<button class="btn btn-danger game-mini-btn" type="button" data-game-delete-match="${match.id}" title="刪除已結束棋局">刪除</button>` : ""}
      </div>
    `;
  }).join("");
  const selected = rows.find((match) => match.id === gameSelectedMatchId) || rows[0];
  if (selected) {
    gameSelectedMatchId = selected.id;
    renderChessBoard(selected);
  }
}

function renderChessBoard(match) {
  const board = $("chess-board");
  const title = $("game-current-title");
  const status = $("game-current-status");
  const history = $("game-move-history");
  const resign = $("game-resign-btn");
  if (!board) return;
  if (!match) {
    board.innerHTML = "<div class=\"chess-empty\">尚未選擇棋局</div>";
    if (title) title.textContent = "尚未選擇棋局";
    if (status) status.textContent = "選擇棋局後即可走棋";
    if (history) history.innerHTML = "";
    if (resign) resign.style.display = "none";
    return;
  }
  const boardMap = match.board || {};
  if (title) title.textContent = gameMatchLabel(match);
  const myTurn = match.status === "active" && match.my_side === match.current_turn;
  if (status) {
    if (match.status !== "active") {
      status.textContent = match.winner_username ? `已結束，勝者：${match.winner_username}` : `已結束：${match.result_reason || "平手"}`;
    } else {
      status.textContent = myTurn ? "輪到你走棋" : `等待${match.current_turn === "white" ? "白方" : "黑方"}走棋`;
    }
  }
  if (resign) resign.style.display = match.status === "active" ? "" : "none";
  if (gameSelectedSquare && !boardMap[gameSelectedSquare]) gameSelectedSquare = null;
  const legalTargets = new Set((match.legal_moves || [])
    .filter((move) => move.from === gameSelectedSquare)
    .map((move) => move.to));
  const squares = [];
  for (let rank = 8; rank >= 1; rank -= 1) {
    for (const file of "abcdefgh") {
      const square = file + rank;
      const piece = boardMap[square] || "";
      const isDark = (file.charCodeAt(0) + rank) % 2 === 0;
      const selectable = myTurn && piece && ((match.my_side === "white" && piece === piece.toUpperCase()) || (match.my_side === "black" && piece === piece.toLowerCase()));
      squares.push(`
        <button class="chess-square ${isDark ? "dark" : "light"} ${square === gameSelectedSquare ? "selected" : ""} ${legalTargets.has(square) ? "target" : ""}"
                type="button" data-chess-square="${square}" ${match.status !== "active" || chessMoveInFlight ? "disabled" : ""}>
          <span>${sanitize(CHESS_PIECES[piece] || "")}</span>
          <small>${selectable || legalTargets.has(square) ? sanitize(square) : ""}</small>
        </button>
      `);
    }
  }
  board.innerHTML = squares.join("");
  if (history) {
    const moves = Array.isArray(match.move_history) ? match.move_history : [];
    history.innerHTML = moves.length
      ? moves.slice(-16).map((move, index) => `<span>${moves.length - 16 + index + 1 > 0 ? moves.length - 16 + index + 1 : index + 1}. ${sanitize(move.from)}→${sanitize(move.to)}${move.computer ? " · CPU" : ""}</span>`).join("")
      : "<span style=\"color:var(--muted);\">尚未走棋</span>";
  }
}

function renderGameLeaderboard(data) {
  const wrap = $("game-leaderboard-list");
  if (!wrap) return;
  const rows = Array.isArray(data?.leaderboard) ? data.leaderboard : [];
  if (!rows.length) {
    const empty = data?.rank_mode === "score_desc"
      ? "本週尚無高分紀錄"
      : data?.rank_mode === "time_asc"
        ? "本週尚無完成時間紀錄"
        : "本週尚無玩家對戰成績";
    wrap.innerHTML = `<p style="color:var(--muted);">${empty}</p>`;
    return;
  }
  if (data?.rank_mode === "score_desc") {
    wrap.innerHTML = rows.map((row) => `
      <div class="drive-file-row game-list-row">
        <div><strong>#${row.rank} ${sanitize(row.username || "-")}</strong><small>${sanitize(data.difficulty || "standard")} · ${row.attempts || 1} 次挑戰 · ${formatSoloGameTime(row.elapsed_ms || 0)}</small></div>
        <strong>${Number(row.score || 0).toLocaleString()}</strong>
      </div>
    `).join("");
    return;
  }
  if (data?.rank_mode === "guesses_then_time") {
    wrap.innerHTML = rows.map((row) => `
      <div class="drive-file-row game-list-row">
        <div><strong>#${row.rank} ${sanitize(row.username || "-")}</strong><small>猜 ${row.guess_count || 0} 次 · 完成 ${row.attempts || 1} 次</small></div>
        <strong>${formatSoloGameTime(row.elapsed_ms || 0)}</strong>
      </div>
    `).join("");
    return;
  }
  if (data?.rank_mode === "time_asc") {
    wrap.innerHTML = rows.map((row) => `
      <div class="drive-file-row game-list-row">
        <div><strong>#${row.rank} ${sanitize(row.username || "-")}</strong><small>${sanitize(data.difficulty || "standard")} · ${row.attempts || 1} 次完成${row.penalty_seconds ? ` · 加時 ${row.penalty_seconds} 秒` : ""}</small></div>
        <strong>${formatSoloGameTime(row.elapsed_ms || 0)}</strong>
      </div>
    `).join("");
    return;
  }
  wrap.innerHTML = rows.map((row) => `
    <div class="drive-file-row game-list-row">
      <div><strong>#${row.rank} ${sanitize(row.username || "-")}</strong><small>${row.wins || 0} 勝 · ${row.draws || 0} 和 · ${row.losses || 0} 敗</small></div>
      <strong>${row.score || 0}</strong>
    </div>
  `).join("");
}

async function loadSelectedGameLeaderboard() {
  const key = gameSelectedKey || "chess";
  let path = "/games/chess/leaderboard";
  if (key === "sudoku") {
    path = "/games/sudoku/solo-leaderboard";
  } else if (key === "minesweeper") {
    const difficulty = minesweeperConfig().difficulty;
    path = `/games/minesweeper/solo-leaderboard?difficulty=${encodeURIComponent(difficulty)}`;
  } else if (key === "1a2b") {
    path = "/games/1a2b/solo-leaderboard";
  } else if (key === "tetris") {
    path = "/games/tetris/solo-leaderboard";
  } else if (key === "space_shooter") {
    path = "/games/space_shooter/solo-leaderboard";
  }
  const data = await gameRequest(path);
  gameState.leaderboard = data.leaderboard || [];
  renderGameLeaderboard(data);
  const awardBtn = $("game-award-btn");
  if (awardBtn) awardBtn.style.display = currentUser === "root" && key === "chess" ? "" : "none";
  return data;
}

async function submitSoloGameScore(gameKey, state) {
  if (!state || state.scoreSubmitted) return;
  state.scoreSubmitted = true;
  const rawElapsed = soloRawElapsedMs(state);
  const elapsed = soloElapsedMs(state);
  try {
    await gameRequest(`/games/${encodeURIComponent(gameKey)}/solo-scores`, {
      method: "POST",
      body: {
        raw_elapsed_ms: rawElapsed,
        penalty_seconds: Number(state.penaltySeconds || 0),
        elapsed_ms: elapsed,
        difficulty: state.difficulty || "standard",
        puzzle_id: state.puzzleId || "",
        guess_count: Array.isArray(state.guesses) ? state.guesses.length : 0,
        score: Number(state.score || 0),
      },
    });
    await loadSelectedGameLeaderboard();
  } catch (err) {
    state.scoreSubmitted = false;
    setGameMsg(err.message || "成績送出失敗", false);
  }
}

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

function generateOneA2BSecret() {
  const digits = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];
  const secret = [];
  while (secret.length < 4) {
    const index = Math.floor(Math.random() * digits.length);
    const digit = digits[index];
    if (!secret.length && digit === "0") continue;
    secret.push(digits.splice(index, 1)[0]);
  }
  return secret.join("");
}

function scoreOneA2BGuess(secret, guess) {
  let a = 0;
  let b = 0;
  for (let i = 0; i < 4; i += 1) {
    if (guess[i] === secret[i]) a += 1;
    else if (secret.includes(guess[i])) b += 1;
  }
  return { a, b };
}

function normalizeOneA2BGuess(value) {
  return String(value || "").replace(/\D/g, "").slice(0, 4);
}

function isValidOneA2BGuess(value) {
  return /^[1-9][0-9]{3}$/.test(value) && new Set(value.split("")).size === 4;
}

function startOneA2BGame() {
  oneA2BState = {
    secret: generateOneA2BSecret(),
    startedAt: Date.now(),
    completedAt: null,
    penaltySeconds: 0,
    scoreSubmitted: false,
    difficulty: "standard",
    puzzleId: "1a2b-4digits",
    guesses: [],
  };
  const input = $("onea2b-guess-input");
  if (input) {
    input.value = "";
    input.disabled = false;
    input.focus();
  }
  renderOneA2BBoard();
  ensureSoloGameTimer();
  updateOneA2BStatus("計時開始。輸入 4 個不重複數字，首位不可為 0，例如 1234。");
}

function renderOneA2BBoard() {
  const board = $("onea2b-history");
  if (!board) return;
  if (!oneA2BState) {
    board.innerHTML = '<div class="single-game-placeholder">按「開始」後才會產生題目並開始計時。</div>';
    return;
  }
  if (!oneA2BState.guesses.length) {
    board.innerHTML = '<div class="single-game-placeholder">尚未猜測。A 是位置正確，B 是數字正確但位置不同。</div>';
    return;
  }
  board.innerHTML = oneA2BState.guesses.map((item, index) => `
    <div class="onea2b-row ${item.a === 4 ? "solved" : ""}">
      <strong>#${index + 1} ${sanitize(item.guess)}</strong>
      <span>${Number(item.a)}A${Number(item.b)}B</span>
    </div>
  `).join("");
}

function updateOneA2BStatus(prefix = "") {
  const status = $("onea2b-status");
  if (!status) return;
  if (!oneA2BState) {
    status.textContent = "按開始後才會產生答案並開始計時。";
    return;
  }
  const time = formatSoloGameTime(soloElapsedMs(oneA2BState));
  if (oneA2BState.completedAt) {
    status.textContent = `完成時間 ${time} · 共 ${oneA2BState.guesses.length} 次`;
    return;
  }
  const activeNotice = oneA2BState.notice && Date.now() < Number(oneA2BState.noticeUntil || 0)
    ? oneA2BState.notice
    : "";
  if (!activeNotice) {
    oneA2BState.notice = "";
    oneA2BState.noticeUntil = 0;
  }
  const head = activeNotice || prefix || "";
  status.textContent = `${head ? `${head} ` : ""}目前時間 ${time} · 已猜 ${oneA2BState.guesses.length} 次`;
}

function submitOneA2BGuess() {
  if (!oneA2BState || oneA2BState.completedAt) return;
  const input = $("onea2b-guess-input");
  const guess = normalizeOneA2BGuess(input?.value || "");
  if (input && input.value !== guess) input.value = guess;
  if (!isValidOneA2BGuess(guess)) {
    setOneA2BNotice("請輸入 4 個不重複數字，首位不可為 0。");
    updateOneA2BStatus();
    return;
  }
  if (oneA2BState.guesses.some((item) => item.guess === guess)) {
    setOneA2BNotice("這組數字已猜過。");
    updateOneA2BStatus();
    return;
  }
  const result = scoreOneA2BGuess(oneA2BState.secret, guess);
  oneA2BState.guesses.push({ guess, ...result });
  if (input) {
    input.value = "";
    input.focus();
  }
  renderOneA2BBoard();
  if (result.a === 4) {
    oneA2BState.completedAt = Date.now();
    if (input) input.disabled = true;
    updateOneA2BStatus();
    stopSoloGameTimerIfIdle();
    if (soloElapsedMs(oneA2BState) > 5 * 60 * 1000) {
      oneA2BState.scoreSubmitted = true;
      setGameMsg("1A2B 已完成，但超過 5 分鐘，不列入排行榜。", false);
      return;
    }
    submitSoloGameScore("1a2b", oneA2BState);
    setGameMsg(`1A2B 完成，成績 ${formatSoloGameTime(soloElapsedMs(oneA2BState))}`, true);
    return;
  }
  updateOneA2BStatus(`${result.a}A${result.b}B`);
}

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

function clearSpaceShooterLoop() {
  if (spaceShooterLoopTimer) {
    clearInterval(spaceShooterLoopTimer);
    spaceShooterLoopTimer = null;
  }
}

function startSpaceShooterGame() {
  clearSpaceShooterLoop();
  spaceShooterState = {
    status: "active",
    startedAt: Date.now(),
    completedAt: null,
    penaltySeconds: 0,
    scoreSubmitted: false,
    difficulty: "standard",
    puzzleId: "space-shooter-standard",
    score: 0,
    lives: 3,
    tick: 0,
    playerX: 180,
    bullets: [],
    enemies: [],
    keys: {},
    lastShotTick: -20,
  };
  renderSpaceShooterBoard();
  ensureSoloGameTimer();
  spaceShooterLoopTimer = setInterval(tickSpaceShooterGame, 50);
  updateSpaceShooterStatus("出擊。方向鍵或 A/D 移動，空白鍵射擊。");
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
    state.bullets.push({ x: state.playerX, y: 448 });
    state.lastShotTick = state.tick;
  }
  if (state.tick % Math.max(14, 34 - Math.floor(state.score / 250)) === 0) {
    state.enemies.push({ x: 24 + Math.random() * 312, y: -18, hp: 1 });
  }
  state.bullets.forEach((bullet) => { bullet.y -= 12; });
  state.enemies.forEach((enemy) => { enemy.y += 3.2 + Math.min(3, state.score / 600); });
  state.bullets = state.bullets.filter((bullet) => bullet.y > -12);
  const remainingEnemies = [];
  state.enemies.forEach((enemy) => {
    let hit = false;
    state.bullets.forEach((bullet) => {
      if (hit) return;
      if (Math.abs(bullet.x - enemy.x) < 18 && Math.abs(bullet.y - enemy.y) < 18) {
        bullet.y = -100;
        hit = true;
        state.score += 25;
      }
    });
    if (hit) return;
    if (Math.abs(state.playerX - enemy.x) < 24 && enemy.y > 420) {
      state.lives -= 1;
      return;
    }
    if (enemy.y > 540) {
      state.lives -= 1;
      return;
    }
    remainingEnemies.push(enemy);
  });
  state.enemies = remainingEnemies;
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
  state.bullets.push({ x: state.playerX, y: 448 });
  state.lastShotTick = state.tick;
  renderSpaceShooterBoard();
}

function handleGameTouchAction(action) {
  if (action === "tetris-left") return moveTetrisPiece(-1, 0);
  if (action === "tetris-right") return moveTetrisPiece(1, 0);
  if (action === "tetris-down") return moveTetrisPiece(0, 1);
  if (action === "tetris-rotate") return rotateTetrisPiece();
  if (action === "tetris-drop") return hardDropTetrisPiece();
  if (action === "shooter-left") return nudgeSpaceShooter(-34);
  if (action === "shooter-right") return nudgeSpaceShooter(34);
  if (action === "shooter-fire") return shootSpaceShooter();
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
  ctx.fillStyle = "#4d7dff";
  ctx.beginPath();
  ctx.moveTo(state.playerX, 430);
  ctx.lineTo(state.playerX - 18, 470);
  ctx.lineTo(state.playerX + 18, 470);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = "#22c79a";
  state.bullets.forEach((bullet) => ctx.fillRect(bullet.x - 2, bullet.y - 10, 4, 12));
  ctx.fillStyle = "#ff4f6d";
  state.enemies.forEach((enemy) => {
    ctx.beginPath();
    ctx.moveTo(enemy.x, enemy.y + 18);
    ctx.lineTo(enemy.x - 16, enemy.y - 12);
    ctx.lineTo(enemy.x + 16, enemy.y - 12);
    ctx.closePath();
    ctx.fill();
  });
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
    status.textContent = `任務結束 · 分數 ${score} · 時間 ${time}`;
  } else {
    status.textContent = `${prefix ? `${prefix} ` : ""}分數 ${score} · 生命 ${spaceShooterState.lives} · 時間 ${time}`;
  }
}

async function loadGameZone() {
  try {
    await fetchCsrfToken({ force: true });
    const [catalog, usersJson, invitesJson, matchesJson] = await Promise.all([
      gameRequest("/games/catalog"),
      gameRequest("/games/users"),
      gameRequest("/games/chess/invites"),
      gameRequest("/games/chess/matches"),
    ]);
    gameState = {
      matches: matchesJson.matches || [],
      invites: invitesJson.invites || [],
      leaderboard: [],
    };
    renderGameCatalog(catalog.games || []);
    renderGameUsers(usersJson.users || []);
    renderGameInvites(invitesJson.invites || []);
    renderGameMatches(matchesJson.matches || []);
    await loadSelectedGameLeaderboard();
    setGameMsg("", true);
  } catch (err) {
    setGameMsg(err.message || "遊戲區讀取失敗", false);
  }
}

async function refreshGameZoneAfterMutation(successMessage) {
  try {
    await loadGameZone();
    if (successMessage) setGameMsg(successMessage, true);
  } catch (err) {
    if (successMessage) setGameMsg(successMessage, true);
  }
}

async function createGameInvite() {
  const select = $("game-invite-user");
  const username = select ? select.value : "";
  if (!username) {
    setGameMsg("請先選擇要邀請的玩家；沒有其他玩家時可使用電腦練習。", false);
    return;
  }
  try {
    await gameRequest("/games/chess/invites", { method: "POST", body: { opponent_username: username } });
    setGameMsg("已送出對戰邀請", true);
    await refreshGameZoneAfterMutation("已送出對戰邀請");
  } catch (err) {
    setGameMsg(err.message || "送出邀請失敗", false);
  }
}

async function reviewGameInvite(inviteId, action) {
  try {
    const json = await gameRequest(`/games/chess/invites/${encodeURIComponent(inviteId)}/${encodeURIComponent(action)}`, { method: "POST", body: {} });
    if (json.match_id) gameSelectedMatchId = json.match_id;
    setGameMsg("邀請已更新", true);
    await refreshGameZoneAfterMutation("邀請已更新");
  } catch (err) {
    setGameMsg(err.message || "邀請處理失敗", false);
  }
}

async function createPracticeGame() {
  try {
    const side = $("game-practice-side")?.value || "white";
    const difficulty = $("game-practice-difficulty")?.value || "normal";
    const json = await gameRequest("/games/chess/practice", { method: "POST", body: { side, difficulty } });
    gameSelectedMatchId = json.match_id;
    gameSelectedSquare = null;
    const msg = `${side === "black" ? "已建立電腦練習局，你執黑方" : "已建立電腦練習局，你執白方"}，難度：${gameDifficultyLabel(difficulty)}`;
    setGameMsg(msg, true);
    await refreshGameZoneAfterMutation(msg);
  } catch (err) {
    setGameMsg(err.message || "建立練習局失敗", false);
  }
}

async function selectChessSquare(square) {
  if (chessMoveInFlight) return;
  const match = (gameState.matches || []).find((item) => item.id === gameSelectedMatchId);
  if (!match || match.status !== "active") return;
  const piece = match.board?.[square] || "";
  const selectedPiece = gameSelectedSquare ? (match.board?.[gameSelectedSquare] || "") : "";
  const myTurn = match.my_side === match.current_turn;
  const isOwnPiece = piece && ((match.my_side === "white" && piece === piece.toUpperCase()) || (match.my_side === "black" && piece === piece.toLowerCase()));
  const legal = (match.legal_moves || []).some((move) => move.from === gameSelectedSquare && move.to === square);
  if (gameSelectedSquare && !selectedPiece) {
    gameSelectedSquare = null;
    renderChessBoard(match);
    return;
  }
  if (gameSelectedSquare && legal && selectedPiece) {
    const from = gameSelectedSquare;
    gameSelectedSquare = null;
    chessMoveInFlight = true;
    renderChessBoard(match);
    try {
      const json = await gameRequest(`/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/move`, {
        method: "POST",
        body: { from, to: square },
      });
      const updated = json.match;
      gameState.matches = gameState.matches.map((item) => item.id === updated.id ? updated : item);
      renderGameMatches(gameState.matches);
      await loadGameZone();
    } catch (err) {
      setGameMsg(err.message || "走棋失敗", false);
    } finally {
      chessMoveInFlight = false;
      const latest = (gameState.matches || []).find((item) => item.id === gameSelectedMatchId);
      if (latest) renderChessBoard(latest);
    }
    return;
  }
  if (isOwnPiece && myTurn) {
    gameSelectedSquare = square;
    renderChessBoard(match);
  } else if (piece && !myTurn) {
    setGameMsg("還沒輪到你", false);
  }
}

async function resignGame() {
  if (!gameSelectedMatchId) return;
  if (!confirm("確認認輸並結束這局？")) return;
  try {
    await gameRequest(`/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/resign`, { method: "POST", body: {} });
    gameSelectedSquare = null;
    await loadGameZone();
  } catch (err) {
    setGameMsg(err.message || "認輸失敗", false);
  }
}

async function deleteFinishedGame(matchId) {
  const match = (gameState.matches || []).find((item) => String(item.id) === String(matchId));
  if (!match) return;
  if (match.status === "active") {
    setGameMsg("進行中的棋局不能刪除，請先完成棋局或認輸。", false);
    return;
  }
  if (!confirm("確定要從列表刪除這局已結束賽局？排行榜紀錄不會被移除。")) return;
  try {
    await gameRequest(`/games/chess/matches/${encodeURIComponent(matchId)}`, { method: "DELETE", body: {} });
    if (String(gameSelectedMatchId) === String(matchId)) {
      gameSelectedMatchId = null;
      gameSelectedSquare = null;
    }
    await refreshGameZoneAfterMutation("已刪除已結束棋局");
  } catch (err) {
    setGameMsg(err.message || "刪除棋局失敗", false);
  }
}

async function awardGameRewards() {
  try {
    const json = await gameRequest("/root/games/chess/weekly-rewards/award", { method: "POST", body: {} });
    setGameMsg(`已發放 ${json.awarded?.length || 0} 筆週獎勵`, true);
    await loadGameZone();
  } catch (err) {
    setGameMsg(err.message || "週獎勵發放失敗", false);
  }
}

document.addEventListener("click", (event) => {
  const catalogBtn = event.target?.closest?.("[data-game-key]");
  if (catalogBtn) {
    switchGameView(catalogBtn.dataset.gameKey || "chess");
    return;
  }
  const sudokuNewBtn = event.target?.closest?.("#sudoku-new-btn");
  if (sudokuNewBtn) {
    startSudokuGame();
    return;
  }
  const sudokuCheckBtn = event.target?.closest?.("#sudoku-check-btn");
  if (sudokuCheckBtn) {
    checkSudokuGame();
    return;
  }
  const minesNewBtn = event.target?.closest?.("#minesweeper-new-btn");
  if (minesNewBtn) {
    startMinesweeperGame();
    return;
  }
  const oneA2BNewBtn = event.target?.closest?.("#onea2b-new-btn");
  if (oneA2BNewBtn) {
    startOneA2BGame();
    return;
  }
  const oneA2BGuessBtn = event.target?.closest?.("#onea2b-guess-btn");
  if (oneA2BGuessBtn) {
    submitOneA2BGuess();
    return;
  }
  const tetrisNewBtn = event.target?.closest?.("#tetris-new-btn");
  if (tetrisNewBtn) {
    startTetrisGame();
    return;
  }
  const tetrisPauseBtn = event.target?.closest?.("#tetris-pause-btn");
  if (tetrisPauseBtn) {
    toggleTetrisPause();
    return;
  }
  const shooterNewBtn = event.target?.closest?.("#space-shooter-new-btn");
  if (shooterNewBtn) {
    startSpaceShooterGame();
    return;
  }
  const gameTouchBtn = event.target?.closest?.("[data-game-touch]");
  if (gameTouchBtn) {
    handleGameTouchAction(gameTouchBtn.dataset.gameTouch || "");
    return;
  }
  const mineBtn = event.target?.closest?.("[data-mine-index]");
  if (mineBtn) {
    revealMinesweeperCell(mineBtn.dataset.mineIndex);
    return;
  }
  const deleteMatchBtn = event.target?.closest?.("[data-game-delete-match]");
  if (deleteMatchBtn) {
    deleteFinishedGame(deleteMatchBtn.dataset.gameDeleteMatch);
    return;
  }
  const inviteBtn = event.target?.closest?.("[data-game-invite]");
  if (inviteBtn) {
    reviewGameInvite(inviteBtn.dataset.gameInvite, inviteBtn.dataset.gameInviteAction || "accept");
    return;
  }
  const matchBtn = event.target?.closest?.("[data-game-match-id]");
  if (matchBtn) {
    gameSelectedMatchId = Number(matchBtn.dataset.gameMatchId || 0);
    gameSelectedSquare = null;
    renderGameMatches(gameState.matches || []);
    return;
  }
  const squareBtn = event.target?.closest?.("[data-chess-square]");
  if (squareBtn) {
    selectChessSquare(squareBtn.dataset.chessSquare || "");
  }
});

document.addEventListener("input", (event) => {
  const sudokuInput = event.target?.closest?.("[data-sudoku-index]");
  if (sudokuInput) {
    updateSudokuCell(Number(sudokuInput.dataset.sudokuIndex || 0), sudokuInput.value || "");
    return;
  }
  const oneA2BInput = event.target?.closest?.("#onea2b-guess-input");
  if (oneA2BInput) {
    oneA2BInput.value = normalizeOneA2BGuess(oneA2BInput.value || "");
  }
});

document.addEventListener("keydown", (event) => {
  const oneA2BInput = event.target?.closest?.("#onea2b-guess-input");
  if (oneA2BInput && event.key === "Enter") {
    event.preventDefault();
    submitOneA2BGuess();
  }
  const tag = String(event.target?.tagName || "").toLowerCase();
  const editing = ["input", "textarea", "select"].includes(tag);
  if (!editing && gameSelectedKey === "tetris" && tetrisState?.status === "active") {
    if (["ArrowLeft", "ArrowRight", "ArrowDown", "ArrowUp", " "].includes(event.key)) {
      event.preventDefault();
    }
    if (event.key === "ArrowLeft") moveTetrisPiece(-1, 0);
    if (event.key === "ArrowRight") moveTetrisPiece(1, 0);
    if (event.key === "ArrowDown") moveTetrisPiece(0, 1);
    if (event.key === "ArrowUp") rotateTetrisPiece();
    if (event.key === " ") hardDropTetrisPiece();
  }
  if (!editing && gameSelectedKey === "space_shooter" && spaceShooterState?.status === "active") {
    if (["ArrowLeft", "ArrowRight", " ", "a", "A", "d", "D"].includes(event.key)) {
      event.preventDefault();
      spaceShooterState.keys[event.key] = true;
    }
  }
});

document.addEventListener("keyup", (event) => {
  if (spaceShooterState?.keys) {
    spaceShooterState.keys[event.key] = false;
  }
});

document.addEventListener("change", (event) => {
  const difficulty = event.target?.closest?.("#minesweeper-difficulty");
  if (!difficulty) return;
  if (gameSelectedKey === "minesweeper") {
    loadSelectedGameLeaderboard().catch((err) => setGameMsg(err.message || "排行榜讀取失敗", false));
  }
});

document.addEventListener("contextmenu", (event) => {
  const mineBtn = event.target?.closest?.("[data-mine-index]");
  if (!mineBtn) return;
  event.preventDefault();
  toggleMinesweeperFlag(mineBtn.dataset.mineIndex);
});
