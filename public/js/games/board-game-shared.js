'use strict';

(function () {
  const { registerScore } = window.HACKME_LOCAL_GAME_HELPERS;
  const GAME_META = {
    reversi: { title: "黑白棋", size: 8 },
    go: { title: "圍棋", size: 9 },
    gomoku: { title: "五子棋", size: 15 },
  };
  const DIFFICULTIES = ["easy", "normal", "hard"];
  const DIFFICULTY_LABELS = { easy: "簡單", normal: "普通", hard: "困難" };
  const AI_SUPPORTED = new Set(["reversi", "go", "gomoku"]);

  function mountLocalDiscGame(api, type) {
    const meta = GAME_META[type] || GAME_META.reversi;
    const size = meta.size;
    const isReversi = type === "reversi";
    const title = meta.title;
    let aiToken = 0;
    api.setTitle(title);
    api.root.innerHTML = `<div class="board-game-grid ${type}" style="--board-size:${size}" aria-label="${title}"></div>`;
    const boardEl = api.root.querySelector(".board-game-grid");
    const state = {
      startedAt: Date.now(),
      board: Array(size * size).fill(""),
      turn: "black",
      finished: false,
      passCount: 0,
      mode: "human",
      aiColor: "white",
      humanColor: "black",
      aiDifficulty: "normal",
      aiThinking: false,
    };
    const idx = (x, y) => y * size + x;
    const xy = (i) => [i % size, Math.floor(i / size)];
    const inBounds = (x, y) => x >= 0 && y >= 0 && x < size && y < size;
    const other = (color) => color === "black" ? "white" : "black";
    const neighbors = (x, y) => [[1, 0], [-1, 0], [0, 1], [0, -1]]
      .map(([dx, dy]) => [x + dx, y + dy])
      .filter(([nx, ny]) => inBounds(nx, ny));
    const count = (color) => state.board.filter((value) => value === color).length;
    const isAiTurn = () => state.mode === "computer" && state.turn === state.aiColor;
    const inputLocked = () => state.aiThinking || isAiTurn();
    const difficultyLabel = () => DIFFICULTY_LABELS[state.aiDifficulty] || "普通";
    const playerOrderLabel = () => state.humanColor === "black" ? "玩家先手" : "玩家後手";
    const setActions = () => {
      const nextModeLabel = state.mode === "computer" ? "玩家對戰" : "對電腦";
      const sideButton = state.mode === "computer"
        ? `<button class="btn game-mini-btn" type="button" data-action="side">${playerOrderLabel()}</button>`
        : "";
      api.setActions(`
        <button class="btn game-mini-btn btn-primary" type="button" data-action="new">新局</button>
        <button class="btn game-mini-btn" type="button" data-action="mode">${nextModeLabel}</button>
        ${sideButton}
        <button class="btn game-mini-btn" type="button" data-action="difficulty">AI ${difficultyLabel()}</button>
        <button class="btn game-mini-btn" type="button" data-action="pass">停一手</button>
        <button class="btn game-mini-btn" type="button" data-action="finish">結算</button>
      `);
    };
    const status = (text) => api.status(text);
    const finish = (winner = "") => {
      state.finished = true;
      state.aiThinking = false;
      aiToken += 1;
      const black = count("black");
      const white = count("white");
      const score = Math.max(1, black * 10 + (black > white ? 200 : 0));
      registerScore(api, score, state, "standard");
      status(`${winner ? `${winner}勝 · ` : ""}結束 · 黑 ${black} / 白 ${white}`);
    };
    const renderStatus = () => {
      if (state.finished) return;
      const side = state.turn === "black" ? "黑" : "白";
      const mode = state.mode === "computer" ? `對電腦 ${difficultyLabel()} · ${playerOrderLabel()}` : "玩家對戰";
      const actor = state.mode === "computer" ? (isAiTurn() ? "AI" : "玩家") : "玩家";
      status(`${state.aiThinking ? "AI 思考中" : `${side}方走`} · ${actor} · 黑 ${count("black")} / 白 ${count("white")} · ${mode}`);
    };
    const render = () => {
      const locked = inputLocked();
      boardEl.innerHTML = state.board.map((value, i) => (
        `<button class="board-game-cell ${value}" type="button" data-i="${i}" aria-label="${i}" ${locked ? "disabled" : ""}>${value ? `<span></span>` : ""}</button>`
      )).join("");
      renderStatus();
      setActions();
    };
    const reversiFlips = (x, y, color) => {
      const opponent = other(color);
      const flips = [];
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
        const line = []; let nx = x + dx, ny = y + dy;
        while (inBounds(nx, ny) && state.board[idx(nx, ny)] === opponent) { line.push(idx(nx, ny)); nx += dx; ny += dy; }
        if (line.length && inBounds(nx, ny) && state.board[idx(nx, ny)] === color) flips.push(...line);
      }
      return flips;
    };
    const liberties = (start, color) => {
      const stack = [start], group = new Set(), libs = new Set();
      while (stack.length) {
        const current = stack.pop(); if (group.has(current)) continue; group.add(current);
        const [x, y] = xy(current);
        for (const [nx, ny] of neighbors(x, y)) {
          const ni = idx(nx, ny), value = state.board[ni];
          if (!value) libs.add(ni); else if (value === color && !group.has(ni)) stack.push(ni);
        }
      }
      return { group, libs };
    };
    const gomokuWin = (x, y, color) => [[1, 0], [0, 1], [1, 1], [1, -1]].some(([dx, dy]) => {
      let total = 1;
      for (const sign of [1, -1]) {
        let nx = x + dx * sign, ny = y + dy * sign;
        while (inBounds(nx, ny) && state.board[idx(nx, ny)] === color) { total += 1; nx += dx * sign; ny += dy * sign; }
      }
      return total >= 5;
    });
    const applyMove = (i) => {
      if (state.finished || state.board[i]) return false;
      const [x, y] = xy(i);
      if (isReversi) {
        const flips = reversiFlips(x, y, state.turn);
        if (!flips.length) return false;
        state.board[i] = state.turn;
        flips.forEach((fi) => { state.board[fi] = state.turn; });
      } else {
        state.board[i] = state.turn;
        if (type === "go") {
          let captured = 0;
          const opponent = other(state.turn);
          for (const [nx, ny] of neighbors(x, y)) {
            const ni = idx(nx, ny);
            if (state.board[ni] !== opponent) continue;
            const group = liberties(ni, opponent);
            if (!group.libs.size) {
              captured += group.group.size;
              group.group.forEach((gi) => { state.board[gi] = ""; });
            }
          }
          const own = liberties(i, state.turn);
          if (!own.libs.size && !captured) {
            state.board[i] = "";
            return false;
          }
        }
        if (type === "gomoku" && gomokuWin(x, y, state.turn)) {
          const winner = state.turn === "black" ? "黑" : "白";
          finish(winner);
          render();
          return true;
        }
      }
      state.passCount = 0;
      state.turn = other(state.turn);
      render();
      queueAiMove();
      return true;
    };
    const passTurn = () => {
      if (state.finished) return;
      state.passCount += 1;
      state.turn = other(state.turn);
      if (state.passCount >= 2) {
        finish();
      } else {
        render();
        queueAiMove();
      }
    };
    const reset = () => {
      aiToken += 1;
      state.startedAt = Date.now();
      state.board = Array(size * size).fill("");
      state.turn = "black";
      state.finished = false;
      state.passCount = 0;
      state.aiColor = other(state.humanColor);
      state.aiThinking = false;
      if (isReversi) {
        state.board[idx(3, 3)] = "white"; state.board[idx(4, 4)] = "white";
        state.board[idx(3, 4)] = "black"; state.board[idx(4, 3)] = "black";
      }
      render();
      queueAiMove();
    };
    const queueAiMove = () => {
      if (!AI_SUPPORTED.has(type) || state.finished || !isAiTurn() || state.aiThinking) return;
      requestAiMove();
    };
    const requestAiMove = async () => {
      const requestToken = ++aiToken;
      state.aiThinking = true;
      render();
      try {
        const json = await api.request(`/games/${encodeURIComponent(api.key)}/ai-move`, {
          method: "POST",
          body: {
            board: state.board,
            turn: state.turn,
            difficulty: state.aiDifficulty,
          },
        });
        if (requestToken !== aiToken || state.finished) return;
        state.aiThinking = false;
        if (json.action === "move" && json.move) {
          applyMove(Number(json.move.index));
        } else if (json.action === "finish") {
          finish();
          render();
        } else {
          passTurn();
        }
      } catch (err) {
        if (requestToken !== aiToken) return;
        state.aiThinking = false;
        status(err.message || "AI 著手失敗");
        render();
      }
    };
    api.onAction = (action) => {
      if (action === "new") reset();
      if (action === "finish") { finish(); render(); }
      if (action === "pass" && !state.finished && !inputLocked()) passTurn();
      if (action === "mode") {
        state.mode = state.mode === "computer" ? "human" : "computer";
        state.aiThinking = false;
        aiToken += 1;
        render();
        queueAiMove();
      }
      if (action === "side" && state.mode === "computer") {
        state.humanColor = other(state.humanColor);
        reset();
      }
      if (action === "difficulty") {
        const next = (DIFFICULTIES.indexOf(state.aiDifficulty) + 1) % DIFFICULTIES.length;
        state.aiDifficulty = DIFFICULTIES[next];
        render();
      }
    };
    api.root.onclick = (event) => {
      const btn = event.target.closest("[data-i]");
      if (!btn || inputLocked()) return;
      applyMove(Number(btn.dataset.i));
    };
    reset();
    return () => { aiToken += 1; };
  }

  window.mountHackmeLocalDiscGame = mountLocalDiscGame;
}());
