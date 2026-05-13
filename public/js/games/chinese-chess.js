'use strict';

(function () {
  const WIDTH = 9;
  const HEIGHT = 10;
  const PALACE_X = new Set([3, 4, 5]);
  const DIFFICULTIES = ["easy", "normal", "hard"];
  const DIFFICULTY_LABELS = { easy: "簡單", normal: "普通", hard: "困難" };
  const PIECE_VALUES = { k: 10000, r: 900, h: 450, c: 480, e: 230, a: 220, p: 120 };
  const PIECE_LABELS = {
    red: { k: "帥", a: "仕", e: "相", h: "傌", r: "俥", c: "炮", p: "兵" },
    black: { k: "將", a: "士", e: "象", h: "馬", r: "車", c: "砲", p: "卒" },
  };

  function idx(x, y) {
    return y * WIDTH + x;
  }

  function xy(index) {
    return [index % WIDTH, Math.floor(index / WIDTH)];
  }

  function inBounds(x, y) {
    return x >= 0 && y >= 0 && x < WIDTH && y < HEIGHT;
  }

  function sideOf(piece) {
    return String(piece || "").split("_")[0] || "";
  }

  function roleOf(piece) {
    return String(piece || "").split("_")[1] || "";
  }

  function opponent(side) {
    return side === "red" ? "black" : "red";
  }

  function sideName(side) {
    return side === "red" ? "紅方" : "黑方";
  }

  function pieceName(piece) {
    const side = sideOf(piece);
    const role = roleOf(piece);
    return PIECE_LABELS[side]?.[role] || "";
  }

  function initialChineseChessBoard() {
    const board = Array(WIDTH * HEIGHT).fill("");
    const back = ["r", "h", "e", "a", "k", "a", "e", "h", "r"];
    back.forEach((role, x) => {
      board[idx(x, 0)] = `black_${role}`;
      board[idx(x, 9)] = `red_${role}`;
    });
    [1, 7].forEach((x) => {
      board[idx(x, 2)] = "black_c";
      board[idx(x, 7)] = "red_c";
    });
    [0, 2, 4, 6, 8].forEach((x) => {
      board[idx(x, 3)] = "black_p";
      board[idx(x, 6)] = "red_p";
    });
    return board;
  }

  function palaceContains(side, x, y) {
    if (!PALACE_X.has(x)) return false;
    return side === "red" ? y >= 7 && y <= 9 : y >= 0 && y <= 2;
  }

  function crossedRiver(side, y) {
    return side === "red" ? y <= 4 : y >= 5;
  }

  function countBetween(board, from, to) {
    const [fx, fy] = xy(from);
    const [tx, ty] = xy(to);
    if (fx !== tx && fy !== ty) return Infinity;
    const dx = Math.sign(tx - fx);
    const dy = Math.sign(ty - fy);
    let x = fx + dx;
    let y = fy + dy;
    let count = 0;
    while (x !== tx || y !== ty) {
      if (board[idx(x, y)]) count += 1;
      x += dx;
      y += dy;
    }
    return count;
  }

  function pushIfValid(board, moves, side, x, y) {
    if (!inBounds(x, y)) return;
    const target = board[idx(x, y)];
    if (!target || sideOf(target) !== side) moves.push(idx(x, y));
  }

  function pseudoMovesForPiece(board, index) {
    const piece = board[index];
    if (!piece) return [];
    const side = sideOf(piece);
    const role = roleOf(piece);
    const [x, y] = xy(index);
    const moves = [];
    if (role === "k") {
      [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dx, dy]) => {
        const nx = x + dx;
        const ny = y + dy;
        if (palaceContains(side, nx, ny)) pushIfValid(board, moves, side, nx, ny);
      });
      for (let ny = y + (side === "red" ? -1 : 1); ny >= 0 && ny < HEIGHT; ny += side === "red" ? -1 : 1) {
        const target = board[idx(x, ny)];
        if (!target) continue;
        if (roleOf(target) === "k" && sideOf(target) !== side) moves.push(idx(x, ny));
        break;
      }
    } else if (role === "a") {
      [[1, 1], [1, -1], [-1, 1], [-1, -1]].forEach(([dx, dy]) => {
        const nx = x + dx;
        const ny = y + dy;
        if (palaceContains(side, nx, ny)) pushIfValid(board, moves, side, nx, ny);
      });
    } else if (role === "e") {
      [[2, 2], [2, -2], [-2, 2], [-2, -2]].forEach(([dx, dy]) => {
        const nx = x + dx;
        const ny = y + dy;
        const eye = idx(x + dx / 2, y + dy / 2);
        if (!inBounds(nx, ny) || board[eye]) return;
        if (side === "red" && ny < 5) return;
        if (side === "black" && ny > 4) return;
        pushIfValid(board, moves, side, nx, ny);
      });
    } else if (role === "h") {
      [[2, 1], [2, -1], [-2, 1], [-2, -1], [1, 2], [1, -2], [-1, 2], [-1, -2]].forEach(([dx, dy]) => {
        const nx = x + dx;
        const ny = y + dy;
        const leg = Math.abs(dx) === 2 ? idx(x + dx / 2, y) : idx(x, y + dy / 2);
        if (inBounds(nx, ny) && !board[leg]) pushIfValid(board, moves, side, nx, ny);
      });
    } else if (role === "r" || role === "c") {
      [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dx, dy]) => {
        let screens = 0;
        let nx = x + dx;
        let ny = y + dy;
        while (inBounds(nx, ny)) {
          const targetIndex = idx(nx, ny);
          const target = board[targetIndex];
          if (role === "r") {
            if (!target) {
              moves.push(targetIndex);
            } else {
              if (sideOf(target) !== side) moves.push(targetIndex);
              break;
            }
          } else if (!target) {
            if (screens === 0) moves.push(targetIndex);
          } else {
            screens += 1;
            if (screens === 2) {
              if (sideOf(target) !== side) moves.push(targetIndex);
              break;
            }
          }
          nx += dx;
          ny += dy;
        }
      });
    } else if (role === "p") {
      const forward = side === "red" ? -1 : 1;
      pushIfValid(board, moves, side, x, y + forward);
      if (crossedRiver(side, y)) {
        pushIfValid(board, moves, side, x - 1, y);
        pushIfValid(board, moves, side, x + 1, y);
      }
    }
    return moves;
  }

  function applyBoardMove(board, from, to) {
    const next = board.slice();
    next[to] = next[from];
    next[from] = "";
    return next;
  }

  function findGeneral(board, side) {
    return board.findIndex((piece) => piece === `${side}_k`);
  }

  function generalsFacing(board) {
    const red = findGeneral(board, "red");
    const black = findGeneral(board, "black");
    if (red < 0 || black < 0) return false;
    const [rx] = xy(red);
    const [bx] = xy(black);
    return rx === bx && countBetween(board, red, black) === 0;
  }

  function isSquareAttacked(board, square, bySide) {
    return board.some((piece, index) => (
      sideOf(piece) === bySide && pseudoMovesForPiece(board, index).includes(square)
    ));
  }

  function isInCheck(board, side) {
    const general = findGeneral(board, side);
    if (general < 0) return true;
    return generalsFacing(board) || isSquareAttacked(board, general, opponent(side));
  }

  function legalMovesFrom(board, index) {
    const piece = board[index];
    if (!piece) return [];
    const side = sideOf(piece);
    return pseudoMovesForPiece(board, index).filter((to) => {
      const next = applyBoardMove(board, index, to);
      return !generalsFacing(next) && !isInCheck(next, side);
    });
  }

  function allLegalMoves(board, side) {
    const moves = [];
    board.forEach((piece, index) => {
      if (sideOf(piece) !== side) return;
      legalMovesFrom(board, index).forEach((to) => moves.push({ from: index, to }));
    });
    return moves;
  }

  function moveScore(board, move, side, difficulty) {
    const captured = board[move.to];
    const next = applyBoardMove(board, move.from, move.to);
    let score = (PIECE_VALUES[roleOf(captured)] || 0) * 10;
    const [tx, ty] = xy(move.to);
    score += 18 - Math.abs(tx - 4) - Math.abs(ty - (side === "red" ? 2 : 7));
    if (isInCheck(next, opponent(side))) score += 180;
    if (!allLegalMoves(next, opponent(side)).length) score += 50000;
    if (difficulty === "hard") {
      score += allLegalMoves(next, side).length * 2;
      score -= isSquareAttacked(next, move.to, opponent(side)) ? (PIECE_VALUES[roleOf(next[move.to])] || 0) * 2 : 0;
    }
    return score;
  }

  function chooseAiMove(state) {
    const moves = allLegalMoves(state.board, state.turn);
    if (!moves.length) return null;
    const ranked = moves.map((move) => ({
      ...move,
      score: moveScore(state.board, move, state.turn, state.aiDifficulty),
    })).sort((a, b) => b.score - a.score || a.from - b.from || a.to - b.to);
    if (state.aiDifficulty === "easy") {
      const pool = ranked.slice(0, Math.min(6, ranked.length));
      return pool[Math.floor(Math.random() * pool.length)];
    }
    if (state.aiDifficulty === "normal") {
      return ranked[Math.random() < 0.18 ? Math.min(2, ranked.length - 1) : 0];
    }
    return ranked[0];
  }

  function mountChineseChess(api) {
    let aiToken = 0;
    const state = {
      startedAt: Date.now(),
      completedAt: null,
      board: initialChineseChessBoard(),
      turn: "red",
      selected: null,
      targets: new Set(),
      mode: "human",
      humanSide: "red",
      aiSide: "black",
      aiDifficulty: "normal",
      aiThinking: false,
      finished: false,
      winner: "",
      captures: { red: 0, black: 0 },
      moves: 0,
      dailyChallenge: api.dailyChallenge?.() || null,
    };
    api.setTitle("中國象棋");
    api.root.innerHTML = `
      <div class="xiangqi-shell">
        <div class="xiangqi-status-strip" data-xiangqi-info>紅方先行，將帥不可照面。</div>
        <div class="xiangqi-board" aria-label="中國象棋棋盤"></div>
      </div>
    `;
    const boardEl = api.root.querySelector(".xiangqi-board");
    const infoEl = api.root.querySelector("[data-xiangqi-info]");

    const isHumanTurn = () => state.mode !== "computer" || state.turn === state.humanSide;
    const inputLocked = () => state.finished || state.aiThinking || !isHumanTurn();
    const difficultyLabel = () => DIFFICULTY_LABELS[state.aiDifficulty] || "普通";
    const sideButtonLabel = () => state.humanSide === "red" ? "玩家紅方先手" : "玩家黑方後手";

    function setActions() {
      api.setActions(`
        <button class="btn game-mini-btn btn-primary" type="button" data-action="new">新局</button>
        <button class="btn game-mini-btn" type="button" data-action="mode">${state.mode === "computer" ? "線上雙人" : "對電腦"}</button>
        ${state.mode === "computer" ? `<button class="btn game-mini-btn" type="button" data-action="side">${sideButtonLabel()}</button>` : ""}
        <button class="btn game-mini-btn" type="button" data-action="difficulty">AI ${difficultyLabel()}</button>
        <button class="btn game-mini-btn" type="button" data-action="hint">提示</button>
        <button class="btn game-mini-btn" type="button" data-action="resign">認輸</button>
      `);
    }

    function statusText() {
      if (state.finished) {
        return `${sideName(state.winner)}勝 · 結束 · 紅吃 ${state.captures.red} / 黑吃 ${state.captures.black}`;
      }
      const check = isInCheck(state.board, state.turn) ? " · 將軍" : "";
      const actor = state.mode === "computer" ? (isHumanTurn() ? "玩家" : "AI") : "玩家";
      return `${state.aiThinking ? "AI 思考中" : `${sideName(state.turn)}走`} · ${actor}${check} · 紅吃 ${state.captures.red} / 黑吃 ${state.captures.black}`;
    }

    function finish(winner) {
      state.finished = true;
      state.winner = winner || opponent(state.turn);
      state.completedAt = Date.now();
      aiToken += 1;
      const humanWon = state.winner === state.humanSide;
      if (humanWon) {
        api.achievement?.("xiangqi-win", "象棋勝局", "完成一局中國象棋並獲勝。");
        api.mission?.("win", 1, 1, "中國象棋勝局");
      }
      api.mission?.("capture-5", Math.max(state.captures.red, state.captures.black), 5, "吃子 5 枚");
      const score = Math.max(1, (humanWon ? 1800 : 450) + state.captures[state.humanSide] * 120 - state.moves * 2);
      api.submitScore({
        score,
        difficulty: state.mode === "computer" ? `ai-${state.aiDifficulty}` : "pvp",
        puzzle_id: state.dailyChallenge?.key || api.key,
        raw_elapsed_ms: Math.max(1, Date.now() - state.startedAt),
        elapsed_ms: Math.max(1, Date.now() - state.startedAt),
        penalty_seconds: 0,
        guess_count: 0,
        moves: state.moves,
        capture: state.captures[state.humanSide],
        win: humanWon ? 1 : 0,
      });
      render();
    }

    function movePiece(from, to) {
      const piece = state.board[from];
      const captured = state.board[to];
      if (!piece || sideOf(piece) !== state.turn) return false;
      if (!legalMovesFrom(state.board, from).includes(to)) return false;
      state.board = applyBoardMove(state.board, from, to);
      state.selected = null;
      state.targets = new Set();
      state.moves += 1;
      if (captured) {
        state.captures[state.turn] += 1;
        if (roleOf(piece) === "c") api.achievement?.("xiangqi-cannon", "炮打隔山", "用炮吃子。");
      }
      const nextSide = opponent(state.turn);
      if (roleOf(captured) === "k" || !allLegalMoves(state.board, nextSide).length) {
        finish(state.turn);
        return true;
      }
      state.turn = nextSide;
      render();
      queueAiMove();
      return true;
    }

    function render() {
      if (infoEl) infoEl.textContent = statusText();
      const legalTargets = state.targets;
      const checked = isInCheck(state.board, state.turn) ? findGeneral(state.board, state.turn) : -1;
      const cells = state.board.map((piece, index) => {
        const [x, y] = xy(index);
        const side = sideOf(piece);
        const role = roleOf(piece);
        const selected = state.selected === index;
        const target = legalTargets.has(index);
        return `
          <button class="xiangqi-cell ${side} ${role ? `piece-${role}` : ""} ${selected ? "selected" : ""} ${target ? "target" : ""} ${checked === index ? "checked" : ""}"
                  type="button" data-xiangqi-i="${index}" aria-label="${x + 1}-${y + 1} ${pieceName(piece) || "空位"}" ${inputLocked() ? "disabled" : ""}>
            ${piece ? `<span>${pieceName(piece)}</span>` : ""}
          </button>
        `;
      }).join("");
      const overlay = state.finished
        ? `<div class="single-game-over-overlay">CHECKMATE<br><small>${sideName(state.winner)}勝 · ${state.moves} 手</small></div>`
        : "";
      boardEl.innerHTML = `<div class="xiangqi-river" aria-hidden="true">楚河　　漢界</div>${cells}${overlay}`;
      api.status(statusText());
      setActions();
    }

    function reset() {
      aiToken += 1;
      state.startedAt = Date.now();
      state.completedAt = null;
      state.board = initialChineseChessBoard();
      state.turn = "red";
      state.selected = null;
      state.targets = new Set();
      state.aiSide = opponent(state.humanSide);
      state.aiThinking = false;
      state.finished = false;
      state.winner = "";
      state.captures = { red: 0, black: 0 };
      state.moves = 0;
      state.dailyChallenge = api.dailyChallenge?.() || null;
      render();
      queueAiMove();
    }

    function showHint() {
      if (state.finished || !isHumanTurn()) return;
      const moves = allLegalMoves(state.board, state.turn)
        .map((move) => ({ ...move, score: moveScore(state.board, move, state.turn, "hard") }))
        .sort((a, b) => b.score - a.score);
      const best = moves[0];
      if (!best) return;
      state.selected = best.from;
      state.targets = new Set([best.to]);
      api.status(`提示：${pieceName(state.board[best.from])} 可走 ${xy(best.to).map((value) => value + 1).join("-")}`);
      render();
    }

    function queueAiMove() {
      if (state.mode !== "computer" || state.finished || state.turn !== state.aiSide || state.aiThinking) return;
      const requestToken = ++aiToken;
      state.aiThinking = true;
      render();
      window.setTimeout(() => {
        if (requestToken !== aiToken || state.finished || state.turn !== state.aiSide) return;
        const move = chooseAiMove(state);
        state.aiThinking = false;
        if (!move) finish(opponent(state.turn));
        else movePiece(move.from, move.to);
      }, 260);
    }

    api.onAction = (action) => {
      if (action === "new") reset();
      if (action === "mode") {
        state.mode = state.mode === "computer" ? "human" : "computer";
        state.selected = null;
        state.targets = new Set();
        render();
        queueAiMove();
      }
      if (action === "side" && state.mode === "computer") {
        state.humanSide = opponent(state.humanSide);
        reset();
      }
      if (action === "difficulty") {
        const next = (DIFFICULTIES.indexOf(state.aiDifficulty) + 1) % DIFFICULTIES.length;
        state.aiDifficulty = DIFFICULTIES[next];
        render();
      }
      if (action === "hint") showHint();
      if (action === "resign" && !state.finished) finish(opponent(state.turn));
    };

    api.root.onclick = (event) => {
      const button = event.target.closest("[data-xiangqi-i]");
      if (!button || inputLocked()) return;
      const index = Number(button.dataset.xiangqiI);
      const piece = state.board[index];
      if (state.selected !== null && state.targets.has(index)) {
        movePiece(state.selected, index);
        return;
      }
      if (piece && sideOf(piece) === state.turn) {
        state.selected = index;
        state.targets = new Set(legalMovesFrom(state.board, index));
      } else {
        state.selected = null;
        state.targets = new Set();
      }
      render();
    };

    reset();
    return () => { aiToken += 1; };
  }

  window.registerHackmeLocalGameModule("chinese_chess", {
    mount: mountChineseChess,
  });
}());
