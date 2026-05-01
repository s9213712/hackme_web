'use strict';

let gameSelectedMatchId = null;
let gameSelectedSquare = null;
let gameSelectedKey = "chess";
let gameState = { matches: [], invites: [], leaderboard: [] };
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

function setGameMsg(text, ok) {
  const el = $("game-msg");
  if (!el) return;
  el.textContent = text || "";
  el.className = text ? "msg show " + (ok ? "ok" : "err") : "msg";
}

function gameIcon(key) {
  if (key === "sudoku") return "9";
  if (key === "minesweeper") return "!";
  return "♟";
}

function gameSubtitle(game) {
  if (game.key === "sudoku") return "單人邏輯解題";
  if (game.key === "minesweeper") return "單人推理挑戰";
  return game.supports_computer ? "玩家對戰 / 電腦練習" : "玩家對戰";
}

function switchGameView(key) {
  gameSelectedKey = key || "chess";
  const isChess = gameSelectedKey === "chess";
  const chessLobby = $("chess-lobby-panel");
  const chessPanel = $("chess-game-panel");
  const sudokuPanel = $("sudoku-game-panel");
  const minesPanel = $("minesweeper-game-panel");
  if (chessLobby) chessLobby.style.display = isChess ? "" : "none";
  if (chessPanel) chessPanel.style.display = isChess ? "" : "none";
  if (sudokuPanel) sudokuPanel.style.display = gameSelectedKey === "sudoku" ? "" : "none";
  if (minesPanel) minesPanel.style.display = gameSelectedKey === "minesweeper" ? "" : "none";
  document.querySelectorAll("[data-game-key]").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-game-key") === gameSelectedKey);
  });
  if (gameSelectedKey === "sudoku" && !sudokuState) startSudokuGame();
  if (gameSelectedKey === "minesweeper" && !minesweeperState) startMinesweeperGame();
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
  if (difficulty === "hard") return "困難";
  if (difficulty === "normal") return "普通";
  return "簡單";
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
  const legalTargets = new Set((match.legal_moves || [])
    .filter((move) => move.from === gameSelectedSquare)
    .map((move) => move.to));
  const squares = [];
  for (let rank = 8; rank >= 1; rank -= 1) {
    for (const file of "abcdefgh") {
      const square = file + rank;
      const piece = boardMap[square] || "";
      const isDark = (file.charCodeAt(0) + rank) % 2 === 0;
      const selectable = match.status === "active" && piece && ((match.my_side === "white" && piece === piece.toUpperCase()) || (match.my_side === "black" && piece === piece.toLowerCase()));
      squares.push(`
        <button class="chess-square ${isDark ? "dark" : "light"} ${square === gameSelectedSquare ? "selected" : ""} ${legalTargets.has(square) ? "target" : ""}"
                type="button" data-chess-square="${square}" ${match.status !== "active" ? "disabled" : ""}>
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
    wrap.innerHTML = "<p style=\"color:var(--muted);\">本週尚無玩家對戰成績</p>";
    return;
  }
  wrap.innerHTML = rows.map((row) => `
    <div class="drive-file-row game-list-row">
      <div><strong>#${row.rank} ${sanitize(row.username || "-")}</strong><small>${row.wins || 0} 勝 · ${row.draws || 0} 和 · ${row.losses || 0} 敗</small></div>
      <strong>${row.score || 0}</strong>
    </div>
  `).join("");
}

function startSudokuGame() {
  const item = SUDOKU_PUZZLES[Math.floor(Math.random() * SUDOKU_PUZZLES.length)];
  sudokuState = {
    puzzle: item.puzzle,
    solution: item.solution,
    values: item.puzzle.split("").map((value) => value === "0" ? "" : value),
    fixed: item.puzzle.split("").map((value) => value !== "0"),
  };
  renderSudokuBoard();
  const status = $("sudoku-status");
  if (status) status.textContent = "填入 1-9，完成後檢查答案。";
}

function renderSudokuBoard() {
  const board = $("sudoku-board");
  if (!board || !sudokuState) return;
  board.innerHTML = sudokuState.values.map((value, index) => {
    const fixed = sudokuState.fixed[index];
    const row = Math.floor(index / 9);
    const col = index % 9;
    return `
      <input class="sudoku-cell ${fixed ? "fixed" : ""}" inputmode="numeric" maxlength="1"
             aria-label="數獨第 ${row + 1} 列第 ${col + 1} 欄"
             data-sudoku-index="${index}" value="${sanitize(value || "")}" ${fixed ? "readonly" : ""} />
    `;
  }).join("");
}

function updateSudokuCell(index, value) {
  if (!sudokuState || sudokuState.fixed[index]) return;
  const normalized = /^[1-9]$/.test(value || "") ? value : "";
  sudokuState.values[index] = normalized;
  const input = document.querySelector(`[data-sudoku-index="${index}"]`);
  if (input && input.value !== normalized) input.value = normalized;
}

function checkSudokuGame() {
  const status = $("sudoku-status");
  if (!sudokuState) return;
  const current = sudokuState.values.join("");
  document.querySelectorAll("[data-sudoku-index]").forEach((input) => {
    const index = Number(input.getAttribute("data-sudoku-index") || 0);
    input.classList.toggle("wrong", !!sudokuState.values[index] && sudokuState.values[index] !== sudokuState.solution[index]);
  });
  if (sudokuState.values.some((value) => !value)) {
    if (status) status.textContent = "尚未填完。紅色格子代表目前填錯。";
    return;
  }
  if (current === sudokuState.solution) {
    if (status) status.textContent = "完成，答案正確。";
    setGameMsg("數獨完成", true);
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
    status: "ready",
    firstMove: true,
    cells: Array.from({ length: total }, () => ({ mine: false, revealed: false, flagged: false, count: 0 })),
  };
  renderMinesweeperBoard();
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
  state.status = "active";
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
    state.cells.forEach((item) => { if (item.mine) item.revealed = true; });
    renderMinesweeperBoard();
    updateMinesweeperStatus();
    return;
  }
  if (cell.count === 0) {
    minesweeperNeighbors(index).forEach((neighbor) => {
      if (!state.cells[neighbor].revealed) revealMinesweeperCell(neighbor);
    });
  }
  if (state.cells.every((item) => item.mine || item.revealed)) {
    state.status = "won";
    state.cells.forEach((item) => { if (item.mine) item.flagged = true; });
    setGameMsg("踩地雷完成", true);
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
  if (!board || !state) return;
  board.style.setProperty("--mine-cols", String(state.cols));
  board.innerHTML = state.cells.map((cell, index) => {
    const label = cell.revealed ? (cell.mine ? "*" : (cell.count || "")) : (cell.flagged ? "⚑" : "");
    const tone = cell.revealed && cell.mine ? "mine" : cell.revealed ? "revealed" : cell.flagged ? "flagged" : "";
    return `<button class="mine-cell ${tone}" type="button" data-mine-index="${index}">${sanitize(String(label))}</button>`;
  }).join("");
}

function updateMinesweeperStatus() {
  const status = $("minesweeper-status");
  if (!status || !minesweeperState) return;
  const flagged = minesweeperState.cells.filter((cell) => cell.flagged).length;
  if (minesweeperState.status === "won") {
    status.textContent = "完成，所有安全格都已翻開。";
  } else if (minesweeperState.status === "lost") {
    status.textContent = "踩到地雷，請重開一局。";
  } else {
    status.textContent = `地雷 ${minesweeperState.mines} · 已插旗 ${flagged} · 左鍵翻格，右鍵插旗。`;
  }
}

async function loadGameZone() {
  try {
    await fetchCsrfToken({ force: true });
    const [catalog, usersJson, invitesJson, matchesJson, leaderboardJson] = await Promise.all([
      gameRequest("/games/catalog"),
      gameRequest("/games/users"),
      gameRequest("/games/chess/invites"),
      gameRequest("/games/chess/matches"),
      gameRequest("/games/chess/leaderboard"),
    ]);
    gameState = {
      matches: matchesJson.matches || [],
      invites: invitesJson.invites || [],
      leaderboard: leaderboardJson.leaderboard || [],
    };
    renderGameCatalog(catalog.games || []);
    renderGameUsers(usersJson.users || []);
    renderGameInvites(invitesJson.invites || []);
    renderGameMatches(matchesJson.matches || []);
    renderGameLeaderboard(leaderboardJson);
    const awardBtn = $("game-award-btn");
    if (awardBtn) awardBtn.style.display = currentUser === "root" ? "" : "none";
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
    const difficulty = $("game-practice-difficulty")?.value || "easy";
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
  const match = (gameState.matches || []).find((item) => item.id === gameSelectedMatchId);
  if (!match || match.status !== "active") return;
  const piece = match.board?.[square] || "";
  const legal = (match.legal_moves || []).some((move) => move.from === gameSelectedSquare && move.to === square);
  if (gameSelectedSquare && legal) {
    try {
      const json = await gameRequest(`/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/move`, {
        method: "POST",
        body: { from: gameSelectedSquare, to: square },
      });
      gameSelectedSquare = null;
      const updated = json.match;
      gameState.matches = gameState.matches.map((item) => item.id === updated.id ? updated : item);
      renderGameMatches(gameState.matches);
      await loadGameZone();
    } catch (err) {
      setGameMsg(err.message || "走棋失敗", false);
    }
    return;
  }
  if (piece) {
    gameSelectedSquare = square;
    renderChessBoard(match);
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
  if (!sudokuInput) return;
  updateSudokuCell(Number(sudokuInput.dataset.sudokuIndex || 0), sudokuInput.value || "");
});

document.addEventListener("contextmenu", (event) => {
  const mineBtn = event.target?.closest?.("[data-mine-index]");
  if (!mineBtn) return;
  event.preventDefault();
  toggleMinesweeperFlag(mineBtn.dataset.mineIndex);
});
