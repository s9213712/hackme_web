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
const CHESS_PIPELINE_FALLBACK_COMMANDS = {
  prepare: "python3 scripts/games/chess_replay_prepare.py --replace-output --include-quarantine",
  seed_train: "python3 scripts/games/chess_seed_train.py --preset standard",
  exp3_refine: "python3 scripts/games/chess_exp3_dataset_train.py --input-jsonl runtime/reports/games/chess_datasets/train.jsonl",
  benchmark: "python3 scripts/games/chess_self_play_train.py --exp1-games 0 --exp2-games 0 --exp3-games 0 --exp4-games 0 --hard-exp1-games 0 --hard-exp2-games 0 --hard-exp3-games 0 --hard-exp4-games 0 --cross-games 0 --cross-exp1-exp3-games 0 --cross-exp2-exp3-games 0 --cross-exp1-exp4-games 0 --cross-exp2-exp4-games 0 --cross-exp3-exp4-games 0 --benchmark-rounds 1 --smoke-games-per-pair 1",
  full_pipeline: "python3 scripts/games/chess_train_pipeline.py --preset standard --include-quarantine",
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

function gameDifficultyOptionDescription(difficulty) {
  if (difficulty === "experiment 5:nnue") return "實驗 5：NNUE + AlphaBeta/PVS";
  if (difficulty === "experiment 4:pv") return "實驗 4：Policy/Value + MCTS";
  if (difficulty === "experiment 3:dl") return "實驗 3：DL 語義平衡學習";
  if (difficulty === "experiment") return "實驗：引擎搜尋 + 對局學習";
  if (difficulty === "hard") return "困難：避免明顯送子";
  return "普通：優先吃子與將軍";
}

function renderChessPracticeDifficultyOptions(games) {
  const select = $("game-practice-difficulty");
  if (!select) return;
  const chessGame = (Array.isArray(games) ? games : []).find((game) => game?.key === "chess");
  const rows = Array.isArray(chessGame?.computer_difficulties) && chessGame.computer_difficulties.length
    ? chessGame.computer_difficulties
    : [
        { key: "normal", label: "普通" },
        { key: "hard", label: "困難" },
        { key: "experiment", label: "實驗" },
        { key: "experiment 3:dl", label: "實驗 3：DL 語義平衡" },
        { key: "experiment 4:pv", label: "實驗 4：Policy/Value + MCTS" },
        { key: "experiment 5:nnue", label: "實驗 5：NNUE + AlphaBeta/PVS" },
      ];
  const current = select.value || "normal";
  select.innerHTML = rows.map((row) => {
    const key = String(row?.key || "normal");
    const label = String(row?.label || gameDifficultyLabel(key));
    return `<option value="${sanitize(key)}">${sanitize(gameDifficultyOptionDescription(key) || label)}</option>`;
  }).join("");
  const allowed = new Set(rows.map((row) => String(row?.key || "")));
  select.value = allowed.has(current) ? current : (allowed.has("normal") ? "normal" : String(rows[0]?.key || "normal"));
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
  renderChessPracticeDifficultyOptions(rows);
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
  if (difficulty === "experiment 5:nnue") return "實驗 5：NNUE + AlphaBeta/PVS";
  if (difficulty === "experiment 4:pv") return "實驗 4：Policy/Value + MCTS";
  if (difficulty === "experiment 3:dl") return "實驗 3：DL 語義平衡";
  if (difficulty === "experiment") return "實驗";
  if (difficulty === "hard") return "困難";
  return "普通";
}

function gameOpponentColor(color) {
  return color === "white" ? "black" : "white";
}

function chessKingSquare(boardMap, color) {
  const king = color === "black" ? "k" : "K";
  for (const [square, piece] of Object.entries(boardMap || {})) {
    if (piece === king) return square;
  }
  return "";
}

function normalizeChessUciInput(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-h1-8qrbn]/g, "")
    .slice(0, 5);
}

function chessResultText(match) {
  if (!match || match.status === "active") return "";
  const reason = String(match.result_reason || "");
  const winnerId = String(match.winner_user_id || "");
  const me = String(currentUserId || "");
  if (reason === "resign") {
    if (winnerId && winnerId === me) return "對手已認輸，你獲勝";
    if (winnerId) return `${match.winner_username || "對手"} 因對方認輸獲勝`;
    return "你已認輸，棋局結束";
  }
  if (reason === "checkmate") {
    return match.winner_username ? `將死，勝者：${match.winner_username}` : "將死，棋局結束";
  }
  if (reason === "agreed_draw") return "雙方同意和棋";
  if (reason === "stalemate") return "逼和，棋局結束";
  if (reason === "insufficient_material") return "子力不足，和棋";
  if (reason === "threefold_repetition") return "三次重複，和棋";
  if (reason === "fifty_moves") return "50 步規則，和棋";
  if (reason === "seventyfive_moves") return "75 步規則，和棋";
  if (reason === "fivefold_repetition") return "五次重複，和棋";
  return match.winner_username ? `已結束，勝者：${match.winner_username}` : `已結束：${reason || "平手"}`;
}

function buildOptimisticChessMatch(match, move) {
  if (!match || !move) return match;
  const board = { ...(match.board || {}) };
  const piece = move.piece || board[move.from] || "";
  delete board[move.from];
  if (move.en_passant) {
    const captureRank = (match.current_turn === "white" ? Number(move.to[1]) - 1 : Number(move.to[1]) + 1);
    delete board[`${move.to[0]}${captureRank}`];
  }
  board[move.to] = move.promotion
    ? (match.current_turn === "white" ? String(move.promotion || "q").toUpperCase() : String(move.promotion || "q").toLowerCase())
    : piece;
  if (move.castle) {
    if (move.to === "g1") {
      delete board.h1;
      board.f1 = "R";
    } else if (move.to === "c1") {
      delete board.a1;
      board.d1 = "R";
    } else if (move.to === "g8") {
      delete board.h8;
      board.f8 = "r";
    } else if (move.to === "c8") {
      delete board.a8;
      board.d8 = "r";
    }
  }
  const moveHistory = Array.isArray(match.move_history) ? [...match.move_history] : [];
  moveHistory.push({
    by: match.current_turn,
    from: move.from,
    to: move.to,
    piece,
    captured: move.captured || null,
    promotion: move.promotion || null,
    castle: Boolean(move.castle),
    en_passant: Boolean(move.en_passant),
  });
  return {
    ...match,
    board,
    move_history: moveHistory,
    current_turn: gameOpponentColor(match.current_turn),
    legal_moves: [],
    pending_computer_response: true,
    pending_status_message: "你已走棋，電腦思考中...",
  };
}

function resolveChessMoveSelection(match, from, clickedSquare, selectedPiece, clickedPiece) {
  const moves = match.legal_moves || [];
  const direct = moves.filter((move) => move.from === from && move.to === clickedSquare);
  if (direct.length) {
    return { moves: direct, to: clickedSquare, castleByRookClick: false };
  }
  const isKing = selectedPiece === "K" || selectedPiece === "k";
  const isOwnRook = clickedPiece
    && ((match.my_side === "white" && clickedPiece === "R") || (match.my_side === "black" && clickedPiece === "r"));
  if (!isKing || !isOwnRook) return { moves: [], to: clickedSquare, castleByRookClick: false };
  const rank = match.my_side === "white" ? "1" : "8";
  const castleTo = clickedSquare === `h${rank}` ? `g${rank}` : (clickedSquare === `a${rank}` ? `c${rank}` : "");
  if (!castleTo) return { moves: [], to: clickedSquare, castleByRookClick: false };
  const castleMoves = moves.filter((move) => move.from === from && move.to === castleTo && move.castle);
  return { moves: castleMoves, to: castleTo, castleByRookClick: castleMoves.length > 0 };
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
    const meta = match.status === "active"
      ? `${match.current_turn === "white" ? "白方走" : "黑方走"}`
      : chessResultText(match);
    return `
      <div class="game-match-item ${match.id === gameSelectedMatchId ? "active" : ""}">
        <button class="game-match-row ${match.id === gameSelectedMatchId ? "active" : ""}" type="button" data-game-match-id="${match.id}">
          <span><strong>${sanitize(gameMatchLabel(match))}</strong><small>${sanitize(match.status)} · ${sanitize(meta)}</small></span>
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
  const uciInput = $("game-chess-uci-input");
  const uciSubmit = $("game-chess-uci-submit-btn");
  const resign = $("game-resign-btn");
  const offerDraw = $("game-offer-draw-btn");
  const acceptDraw = $("game-accept-draw-btn");
  const rejectDraw = $("game-reject-draw-btn");
  const claimDraw = $("game-claim-draw-btn");
  if (!board) return;
  if (!match) {
    board.innerHTML = "<div class=\"chess-empty\">尚未選擇棋局</div>";
    if (title) title.textContent = "尚未選擇棋局";
    if (status) status.textContent = "選擇棋局後即可走棋";
    if (history) history.innerHTML = "";
    if (uciInput) {
      uciInput.value = "";
      uciInput.disabled = true;
    }
    if (uciSubmit) uciSubmit.disabled = true;
    if (resign) resign.style.display = "none";
    if (offerDraw) offerDraw.style.display = "none";
    if (acceptDraw) acceptDraw.style.display = "none";
    if (rejectDraw) rejectDraw.style.display = "none";
    if (claimDraw) claimDraw.style.display = "none";
    return;
  }
  const boardMap = match.board || {};
  if (title) title.textContent = gameMatchLabel(match);
  const myTurn = match.status === "active" && match.my_side === match.current_turn;
  if (uciInput) uciInput.disabled = !myTurn || chessMoveInFlight;
  if (uciSubmit) uciSubmit.disabled = !myTurn || chessMoveInFlight;
  if (status) {
    if (match.status !== "active") {
      status.textContent = match.winner_username ? `已結束，勝者：${match.winner_username}` : `已結束：${match.result_reason || "平手"}`;
    } else if (match.draw_offer_pending && match.can_accept_draw_offer) {
      status.textContent = `${match.draw_offer_by_username || "對手"} 已提和，等待你接受或拒絕`;
    } else if (match.draw_offer_pending && String(match.draw_offer_by_user_id || "") === String(currentUserId || "")) {
      status.textContent = `已向 ${match.my_side === "white" ? match.black_username : match.white_username} 提和，等待對方回覆`;
    } else if (match.pending_computer_response) {
      status.textContent = match.pending_status_message || "你已走棋，電腦思考中...";
    } else {
      status.textContent = myTurn ? "輪到你走棋" : `等待${match.current_turn === "white" ? "白方" : "黑方"}走棋`;
    }
  }
  if (resign) resign.style.display = match.status === "active" ? "" : "none";
  if (offerDraw) offerDraw.style.display = match.status === "active" && match.can_offer_draw ? "" : "none";
  if (acceptDraw) acceptDraw.style.display = match.status === "active" && match.can_accept_draw_offer ? "" : "none";
  if (rejectDraw) rejectDraw.style.display = match.status === "active" && match.can_reject_draw_offer ? "" : "none";
  if (claimDraw) claimDraw.style.display = match.status === "active" && myTurn && match.can_claim_draw ? "" : "none";
  if (gameSelectedSquare && !boardMap[gameSelectedSquare]) gameSelectedSquare = null;
  const legalTargets = new Set((match.legal_moves || [])
    .filter((move) => move.from === gameSelectedSquare)
    .map((move) => move.to));
  const specialTargets = new Map((match.legal_moves || [])
    .filter((move) => move.from === gameSelectedSquare && (move.castle || move.en_passant || move.promotion))
    .map((move) => [move.to, move]));
  const checkmatedKingSquare = match.status !== "active" && match.result_reason === "checkmate"
    ? chessKingSquare(boardMap, match.current_turn)
    : "";
  const squares = [];
  for (let rank = 8; rank >= 1; rank -= 1) {
    for (const file of "abcdefgh") {
      const square = file + rank;
      const piece = boardMap[square] || "";
      const isDark = (file.charCodeAt(0) + rank) % 2 === 0;
      const selectable = myTurn && piece && ((match.my_side === "white" && piece === piece.toUpperCase()) || (match.my_side === "black" && piece === piece.toLowerCase()));
      const special = specialTargets.get(square);
      const specialClass = special?.castle ? " castle-target" : (special?.en_passant ? " en-passant-target" : (special?.promotion ? " promotion-target" : ""));
      const specialLabel = special?.castle ? "王車易位" : (special?.en_passant ? "吃過路兵" : (special?.promotion ? "升變" : ""));
      squares.push(`
        <button class="chess-square ${isDark ? "dark" : "light"} ${square === gameSelectedSquare ? "selected" : ""} ${legalTargets.has(square) ? `target${specialClass}` : ""} ${square === checkmatedKingSquare ? "checkmated-king" : ""}"
                type="button" data-chess-square="${square}" title="${sanitize(specialLabel || square)}" ${match.status !== "active" || chessMoveInFlight ? "disabled" : ""}>
          <span>${sanitize(CHESS_PIECES[piece] || "")}</span>
          <small>${specialLabel ? sanitize(specialLabel) : (selectable || legalTargets.has(square) ? sanitize(square) : "")}</small>
        </button>
      `);
    }
  }
  board.innerHTML = `
    <div class="chess-rank-labels" aria-hidden="true">${[8, 7, 6, 5, 4, 3, 2, 1].map((rank) => `<span>${rank}</span>`).join("")}</div>
    <div class="chess-board-grid">${squares.join("")}</div>
    <div class="chess-file-labels" aria-hidden="true">${"abcdefgh".split("").map((file) => `<span>${file}</span>`).join("")}</div>
  `;
  if (history) {
    const moves = Array.isArray(match.move_history) ? match.move_history : [];
    history.innerHTML = moves.length
      ? moves.slice(-16).map((move, index) => `<span>${moves.length - 16 + index + 1 > 0 ? moves.length - 16 + index + 1 : index + 1}. ${sanitize(move.from)}→${sanitize(move.to)}${move.computer ? " · CPU" : ""}</span>`).join("")
      : "<span style=\"color:var(--muted);\">尚未走棋</span>";
  }
}

async function submitChessMove(match, chosenMove, { from, to, promotion = null, optimisticMessage = "已送出走棋，等待電腦回應..." } = {}) {
  if (!match || chessMoveInFlight) return;
  const previousMatch = match;
  const optimisticMatch = buildOptimisticChessMatch(match, chosenMove);
  gameSelectedSquare = null;
  chessMoveInFlight = true;
  gameState.matches = gameState.matches.map((item) => item.id === previousMatch.id ? optimisticMatch : item);
  renderGameMatches(gameState.matches);
  setGameMsg(optimisticMessage, true);
  try {
    const json = await gameRequest(`/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/move`, {
      method: "POST",
      body: { from, to, promotion },
    });
    const updated = json.match;
    gameState.matches = gameState.matches.map((item) => item.id === updated.id ? updated : item);
    renderGameMatches(gameState.matches);
    await loadGameZone();
  } catch (err) {
    gameState.matches = gameState.matches.map((item) => item.id === previousMatch.id ? previousMatch : item);
    setGameMsg(err.message || "走棋失敗", false);
  } finally {
    chessMoveInFlight = false;
    const latest = (gameState.matches || []).find((item) => item.id === gameSelectedMatchId);
    if (latest) renderChessBoard(latest);
  }
}

function resolveChessPromotionMove(candidateMoves, requestedPromotion) {
  const normalized = String(requestedPromotion || "").trim().toLowerCase();
  if (normalized) {
    return candidateMoves.find((move) => String(move.promotion || "").toLowerCase() === normalized) || null;
  }
  if (candidateMoves.some((move) => move.promotion)) {
    return candidateMoves.find((move) => String(move.promotion || "").toLowerCase() === "q") || candidateMoves[0] || null;
  }
  return candidateMoves[0] || null;
}

async function submitChessUciMove() {
  if (chessMoveInFlight) return;
  const input = $("game-chess-uci-input");
  const raw = normalizeChessUciInput(input?.value || "");
  if (input) input.value = raw;
  if (!/^[a-h][1-8][a-h][1-8][qrbn]?$/.test(raw)) {
    setGameMsg("UCI 格式需為 d1c2 或 e7e8q。", false);
    return;
  }
  const match = (gameState.matches || []).find((item) => item.id === gameSelectedMatchId);
  if (!match || match.status !== "active") {
    setGameMsg("請先選擇進行中的棋局。", false);
    return;
  }
  if (match.my_side !== match.current_turn) {
    setGameMsg("還沒輪到你", false);
    return;
  }
  const from = raw.slice(0, 2);
  const to = raw.slice(2, 4);
  const requestedPromotion = raw.slice(4, 5);
  const candidateMoves = (match.legal_moves || []).filter((move) => move.from === from && move.to === to);
  if (requestedPromotion && !candidateMoves.some((move) => move.promotion)) {
    setGameMsg(`這步不需要升變棋子：${raw}`, false);
    return;
  }
  const chosenMove = resolveChessPromotionMove(candidateMoves, requestedPromotion);
  if (!chosenMove) {
    setGameMsg(`不是合法走法：${raw}`, false);
    return;
  }
  if (chosenMove.promotion && requestedPromotion && String(chosenMove.promotion || "").toLowerCase() !== requestedPromotion) {
    setGameMsg(`升變棋子不合法：${requestedPromotion}`, false);
    return;
  }
  await submitChessMove(match, chosenMove, {
    from,
    to,
    promotion: chosenMove.promotion || requestedPromotion || null,
    optimisticMessage: `已送出 ${raw}，等待電腦回應...`,
  });
  if (input) input.value = "";
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

function gameRootChessPanelVisible() {
  return currentUser === "root" && gameSelectedKey === "chess";
}

function renderChessRootDashboard(data) {
  const panel = $("game-root-chess-panel");
  const status = $("game-root-chess-status");
  const production = $("game-root-chess-production");
  const replay = $("game-root-chess-replay");
  const pipeline = $("game-root-chess-pipeline");
  const benchmark = $("game-root-chess-benchmark");
  const promotion = $("game-root-chess-promotion");
  const prepareCommand = $("game-root-chess-prepare-command");
  const seedCommand = $("game-root-chess-seed-command");
  const exp3Command = $("game-root-chess-exp3-command");
  const benchmarkCommand = $("game-root-chess-benchmark-command");
  const fullPipelineCommand = $("game-root-chess-pipeline-command");
  if (!panel || !status || !production || !replay || !pipeline || !benchmark || !promotion) return;
  panel.style.display = gameRootChessPanelVisible() ? "" : "none";
  if (!gameRootChessPanelVisible()) return;
  if (!data?.ok) {
    status.textContent = "chess engine dashboard 讀取失敗。";
    return;
  }
  const models = Array.isArray(data.production_models) ? data.production_models : [];
  const replayInfo = data.replay_buffer || {};
  const pipelineInfo = data.pipeline || {};
  const pipelineCommands = pipelineInfo.commands || CHESS_PIPELINE_FALLBACK_COMMANDS;
  const latestPrepare = data.latest_replay_prepare?.summary || {};
  const latestSeed = data.latest_seed_training_report?.summary || {};
  const latestPipeline = data.latest_pipeline_report?.summary || {};
  const bench = data.latest_benchmark?.benchmark || {};
  const smoke = data.latest_benchmark?.smoke_evaluation || {};
  const promo = data.promotion?.status || {};
  const recommendation = data.pipeline_recommendation || {};
  const readyLabel = recommendation.ready ? "可重訓" : "暫不建議重訓";
  status.textContent = `Warm Start ${data.warm_start?.ok ? "已就緒" : "失敗"} · usable replay ${Number(replayInfo.usable_replays || 0)} 筆 · ${readyLabel} · 最近 benchmark ${bench.games_played || 0} 場`;
  production.innerHTML = models.length
    ? models.map((row) => `<div class="drive-file-row game-list-row"><div><strong>${sanitize(row.engine || "-")}</strong><small>${sanitize(row.architecture || row.path || "-")}</small></div><strong>${sanitize(String(row.sample_count ?? row.size_bytes ?? 0))}</strong></div>`).join("")
    : "<p style=\"color:var(--muted);\">尚無 production model</p>";
  replay.innerHTML = `
    <div class="drive-file-row game-list-row"><div><strong>Replay Buffer</strong><small>${sanitize(replayInfo.path || "-")}</small></div><strong>${Number(replayInfo.total_replays || 0)}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Usable Replays</strong><small>trusted / trainable</small></div><strong>${Number(replayInfo.usable_replays || 0)}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Quarantine</strong><small>${sanitize(replayInfo.quarantine_path || "-")}</small></div><strong>${Number(replayInfo.quarantine_replays || 0)}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Rejected</strong><small>${sanitize(replayInfo.rejected_path || "-")}</small></div><strong>${Number(replayInfo.rejected_replays || 0)}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Recent User Games</strong><small>最近 7 天</small></div><strong>${Number(replayInfo.recent_user_games || 0)}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Suspicious Replays</strong><small>待降權 / 隔離</small></div><strong>${Number(replayInfo.suspicious_count || 0)}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Duplicate / Resign Abuse</strong><small>資料污染風險</small></div><strong>${Number(replayInfo.duplicate_count || 0)} / ${Number(replayInfo.resign_abuse_count || 0)}</strong></div>
  `;
  pipeline.innerHTML = `
    <div class="drive-file-row game-list-row"><div><strong>Retrain Recommendation</strong><small>${sanitize((recommendation.ready_reasons || recommendation.blocked_reasons || []).join(", ") || "no signal")}</small></div><strong>${recommendation.ready ? "READY" : "HOLD"}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Latest Prepare</strong><small>${sanitize(data.latest_replay_prepare?.path || "-")}</small></div><strong>${Number(latestPrepare.accepted_train_samples || 0)} / ${Number(latestPrepare.accepted_eval_samples || 0)}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Dataset Paths</strong><small>train / eval</small></div><strong>${sanitize(pipelineInfo.train_path || "-")} | ${sanitize(pipelineInfo.eval_path || "-")}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Latest Seed Train</strong><small>${sanitize(data.latest_seed_training_report?.path || "-")}</small></div><strong>${Number(latestSeed.games_played || 0)}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Latest Updates</strong><small>exp3 / exp4</small></div><strong>${Number((latestSeed.updates || {})["experiment 3:dl"] || 0)} / ${Number((latestSeed.updates || {})["experiment 4:pv"] || 0)}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Latest Full Pipeline</strong><small>${sanitize(data.latest_pipeline_report?.path || "-")}</small></div><strong>${sanitize(latestPipeline.run_id || "-")}</strong></div>
  `;
  const standings = Array.isArray(bench.standings) ? bench.standings.slice(0, 6) : [];
  benchmark.innerHTML = standings.length
    ? standings.map((row) => `<div class="drive-file-row game-list-row"><div><strong>${sanitize(row.engine || "-")}</strong><small>score_rate ${sanitize(String(row.score_rate ?? "-"))} · win_rate ${sanitize(String(row.win_rate ?? "-"))}</small></div><strong>${Number(row.games || 0)}</strong></div>`).join("")
    : "<p style=\"color:var(--muted);\">尚無 benchmark report</p>";
  const candidate = promo.candidate || null;
  const last = promo.last_promotion_result || null;
  promotion.innerHTML = `
    <div class="drive-file-row game-list-row"><div><strong>Current Candidate</strong><small>${sanitize(candidate?.engine || "none")}</small></div><strong>${candidate?.promotion_gate?.pass ? "PASS" : (candidate ? "HOLD" : "-")}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Smoke</strong><small>post-training smoke</small></div><strong>${smoke.pass ? "PASS" : (smoke.games_played ? "FAIL" : "-")}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Promotion Gate</strong><small>${sanitize((candidate?.promotion_gate?.reasons || []).join(", ") || "ready")}</small></div><strong>${candidate?.promotion_gate?.pass ? "PASS" : (candidate ? "HOLD" : "-")}</strong></div>
    <div class="drive-file-row game-list-row"><div><strong>Last Promotion</strong><small>${sanitize(last?.engine || "none")}</small></div><strong>${sanitize(last?.result || "-")}</strong></div>
  `;
  if (prepareCommand) prepareCommand.value = pipelineCommands.prepare || "";
  if (seedCommand) seedCommand.value = pipelineCommands.seed_train || "";
  if (exp3Command) exp3Command.value = pipelineCommands.exp3_refine || "";
  if (benchmarkCommand) benchmarkCommand.value = pipelineCommands.benchmark || "";
  if (fullPipelineCommand) fullPipelineCommand.value = pipelineCommands.full_pipeline || "";
}

async function loadChessRootDashboard() {
  const panel = $("game-root-chess-panel");
  if (panel) panel.style.display = gameRootChessPanelVisible() ? "" : "none";
  if (!gameRootChessPanelVisible()) return;
  const data = await gameRequest("/root/games/chess/engines/dashboard");
  renderChessRootDashboard(data);
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
  await loadChessRootDashboard().catch(() => {});
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
  const resolvedSelection = gameSelectedSquare
    ? resolveChessMoveSelection(match, gameSelectedSquare, square, selectedPiece, piece)
    : { moves: [], to: square, castleByRookClick: false };
  const legal = resolvedSelection.moves.length > 0;
  if (gameSelectedSquare && !selectedPiece) {
    gameSelectedSquare = null;
    renderChessBoard(match);
    return;
  }
  if (gameSelectedSquare && legal && selectedPiece) {
    const from = gameSelectedSquare;
    const targetSquare = resolvedSelection.to || square;
    const candidateMoves = resolvedSelection.moves;
    let chosenMove = candidateMoves[0] || {
      from,
      to: targetSquare,
      piece: selectedPiece,
    };
    let promotion = chosenMove.promotion || null;
    if (candidateMoves.length > 1 && candidateMoves.some((move) => move.promotion)) {
      const raw = window.prompt("兵升變請輸入 q / r / b / n", "q");
      if (raw === null) {
        setGameMsg("已取消升變走棋。", false);
        return;
      }
      const normalized = String(raw || "q").trim().toLowerCase();
      const resolved = ["q", "r", "b", "n"].includes(normalized) ? normalized : "q";
      chosenMove = candidateMoves.find((move) => String(move.promotion || "").toLowerCase() === resolved) || candidateMoves[0];
      promotion = chosenMove.promotion || resolved;
    }
    const previousMatch = match;
    await submitChessMove(previousMatch, chosenMove, { from, to: targetSquare, promotion });
    return;
  }
  if (isOwnPiece && myTurn) {
    gameSelectedSquare = square;
    renderChessBoard(match);
    if ((piece === "K" || piece === "k") && (match.legal_moves || []).some((move) => move.from === square && move.castle)) {
      setGameMsg("可王車易位：點亮起的 g/c 目標格，或直接點同側車。", true);
    }
  } else if (piece && !myTurn) {
    setGameMsg("還沒輪到你", false);
  }
}

async function claimChessDraw() {
  if (!gameSelectedMatchId) {
    setGameMsg("請先選擇要申請和棋的棋局。", false);
    return;
  }
  const match = (gameState.matches || []).find((item) => item.id === gameSelectedMatchId);
  if (!match) {
    setGameMsg("找不到目前棋局，請先刷新遊戲區。", false);
    return;
  }
  if (match.status !== "active") {
    setGameMsg("這局已經結束，不需要再申請和棋。", false);
    return;
  }
  if (!match.can_claim_draw) {
    setGameMsg("目前沒有三次重複或 50 步和棋可申請。", false);
    return;
  }
  try {
    const json = await gameRequest(`/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/claim-draw`, { method: "POST", body: {} });
    gameSelectedSquare = null;
    if (json?.match?.id) {
      gameState.matches = (gameState.matches || []).map((item) => item.id === json.match.id ? json.match : item);
      renderGameMatches(gameState.matches);
    }
    setGameMsg("已申請和棋並結束棋局。", true);
    await loadGameZone();
  } catch (err) {
    setGameMsg(err.message || "申請和棋失敗", false);
  }
}

async function offerChessDraw() {
  if (!gameSelectedMatchId) {
    setGameMsg("請先選擇要提和的棋局。", false);
    return;
  }
  const match = (gameState.matches || []).find((item) => item.id === gameSelectedMatchId);
  if (!match) {
    setGameMsg("找不到目前棋局，請先刷新遊戲區。", false);
    return;
  }
  if (match.status !== "active") {
    setGameMsg("這局已經結束，不能再提和。", false);
    return;
  }
  if (!match.can_offer_draw) {
    setGameMsg("目前不能提和，可能已有待回覆的和棋。", false);
    return;
  }
  try {
    const json = await gameRequest(`/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/offer-draw`, { method: "POST", body: {} });
    gameSelectedSquare = null;
    if (json?.match?.id) {
      gameState.matches = (gameState.matches || []).map((item) => item.id === json.match.id ? json.match : item);
      renderGameMatches(gameState.matches);
    }
    setGameMsg("已提出和棋，等待對方回覆。", true);
    await loadGameZone();
  } catch (err) {
    setGameMsg(err.message || "提和失敗", false);
  }
}

async function respondChessDraw(action) {
  if (!gameSelectedMatchId) {
    setGameMsg(`請先選擇要${action === "accept" ? "接受" : "拒絕"}和棋的棋局。`, false);
    return;
  }
  const match = (gameState.matches || []).find((item) => item.id === gameSelectedMatchId);
  if (!match) {
    setGameMsg("找不到目前棋局，請先刷新遊戲區。", false);
    return;
  }
  if (match.status !== "active") {
    setGameMsg("這局已經結束，不需要再回覆和棋。", false);
    return;
  }
  const canRespond = action === "accept" ? match.can_accept_draw_offer : match.can_reject_draw_offer;
  if (!canRespond) {
    setGameMsg("目前沒有待回覆的和棋。", false);
    return;
  }
  try {
    const json = await gameRequest(`/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/respond-draw`, {
      method: "POST",
      body: { action },
    });
    gameSelectedSquare = null;
    if (json?.match?.id) {
      gameState.matches = (gameState.matches || []).map((item) => item.id === json.match.id ? json.match : item);
      renderGameMatches(gameState.matches);
    }
    setGameMsg(action === "accept" ? "已接受和棋，棋局結束。": "已拒絕和棋。", true);
    await loadGameZone();
  } catch (err) {
    setGameMsg(err.message || `${action === "accept" ? "接受" : "拒絕"}和棋失敗`, false);
  }
}

async function resignGame() {
  if (!gameSelectedMatchId) {
    setGameMsg("請先選擇要認輸的棋局。", false);
    return;
  }
  const match = (gameState.matches || []).find((item) => item.id === gameSelectedMatchId);
  if (!match) {
    setGameMsg("找不到目前棋局，請先刷新遊戲區。", false);
    return;
  }
  if (match.status !== "active") {
    setGameMsg("這局已經結束，不需要再認輸。", false);
    return;
  }
  if (!confirm("確認認輸並結束這局？")) return;
  try {
    const json = await gameRequest(`/games/chess/matches/${encodeURIComponent(gameSelectedMatchId)}/resign`, { method: "POST", body: {} });
    gameSelectedSquare = null;
    if (json?.match?.id) {
      gameState.matches = (gameState.matches || []).map((item) => item.id === json.match.id ? json.match : item);
      renderGameMatches(gameState.matches);
    }
    setGameMsg("已認輸並結束棋局。", true);
    await loadGameZone();
  } catch (err) {
    setGameMsg(err.message || "認輸失敗", false);
  }
}

async function deleteFinishedGame(matchId) {
  const match = (gameState.matches || []).find((item) => String(item.id) === String(matchId));
  if (!match) {
    setGameMsg("找不到要刪除的棋局，請先刷新遊戲區。", false);
    return;
  }
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

async function warmStartChessModels() {
  try {
    const json = await gameRequest("/root/games/chess/warm-start", { method: "POST", body: {} });
    setGameMsg(`warm start 完成，共檢查 ${json.artifacts?.length || 0} 個 artifact`, true);
    await loadChessRootDashboard();
  } catch (err) {
    setGameMsg(err.message || "warm start 失敗", false);
  }
}

async function stageChessCandidate() {
  try {
    const engine = $("game-root-chess-engine")?.value || "experiment 4:pv";
    const sourcePath = $("game-root-chess-candidate-path")?.value || "";
    const benchmarkPath = $("game-root-chess-benchmark-path")?.value || "";
    const json = await gameRequest("/root/games/chess/promotion/stage", {
      method: "POST",
      body: { engine, source_path: sourcePath, benchmark_report_path: benchmarkPath },
    });
    setGameMsg(`candidate staged: ${json.engine}`, true);
    await loadChessRootDashboard();
  } catch (err) {
    setGameMsg(err.message || "stage candidate 失敗", false);
  }
}

async function promoteChessCandidate() {
  try {
    const engine = $("game-root-chess-engine")?.value || "experiment 4:pv";
    const benchmarkPath = $("game-root-chess-benchmark-path")?.value || "";
    const json = await gameRequest("/root/games/chess/promotion/promote", {
      method: "POST",
      body: { engine, benchmark_report_path: benchmarkPath },
    });
    setGameMsg(`promotion 完成: ${json.engine}`, true);
    await loadChessRootDashboard();
  } catch (err) {
    setGameMsg(err.message || "promotion 失敗", false);
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
  const rootRefreshBtn = event.target?.closest?.("#game-root-chess-refresh-btn");
  if (rootRefreshBtn) {
    loadChessRootDashboard().catch((err) => setGameMsg(err.message || "dashboard 讀取失敗", false));
    return;
  }
  const rootWarmStartBtn = event.target?.closest?.("#game-root-chess-warm-start-btn");
  if (rootWarmStartBtn) {
    warmStartChessModels();
    return;
  }
  const rootStageBtn = event.target?.closest?.("#game-root-chess-stage-btn");
  if (rootStageBtn) {
    stageChessCandidate();
    return;
  }
  const rootPromoteBtn = event.target?.closest?.("#game-root-chess-promote-btn");
  if (rootPromoteBtn) {
    promoteChessCandidate();
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
  const offerDrawBtn = event.target?.closest?.("#game-offer-draw-btn");
  if (offerDrawBtn) {
    offerChessDraw();
    return;
  }
  const acceptDrawBtn = event.target?.closest?.("#game-accept-draw-btn");
  if (acceptDrawBtn) {
    respondChessDraw("accept");
    return;
  }
  const rejectDrawBtn = event.target?.closest?.("#game-reject-draw-btn");
  if (rejectDrawBtn) {
    respondChessDraw("reject");
    return;
  }
  const claimDrawBtn = event.target?.closest?.("#game-claim-draw-btn");
  if (claimDrawBtn) {
    claimChessDraw();
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

document.addEventListener("submit", (event) => {
  const uciForm = event.target?.closest?.("#game-chess-uci-form");
  if (!uciForm) return;
  event.preventDefault();
  submitChessUciMove();
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
    return;
  }
  const chessUciInput = event.target?.closest?.("#game-chess-uci-input");
  if (chessUciInput) {
    chessUciInput.value = normalizeChessUciInput(chessUciInput.value || "");
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
