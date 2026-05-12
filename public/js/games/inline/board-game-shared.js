'use strict';

(function () {
  const { makeCtx, registerScore } = window.HACKME_INLINE_GAME_HELPERS;
  function mountInlineDiscGame(api, type) {
    const isReversi = type === "reversi";
    const size = type === "gomoku" ? 15 : (type === "go" ? 9 : 8);
    const title = { reversi: "黑白棋", go: "圍棋", gomoku: "五子棋" }[type];
    makeCtx(api, title);
    api.setActions(`<button class="btn game-mini-btn btn-primary" type="button" data-action="new">新局</button><button class="btn game-mini-btn" type="button" data-action="pass">停一手</button><button class="btn game-mini-btn" type="button" data-action="finish">結算</button>`);
    api.root.innerHTML = `<div class="board-game-grid ${type}" style="--board-size:${size}" aria-label="${title}"></div>`;
    const boardEl = api.root.querySelector(".board-game-grid");
    const state = { startedAt: Date.now(), board: Array(size * size).fill(""), turn: "black", finished: false, passCount: 0 };
    const idx = (x, y) => y * size + x;
    const inBounds = (x, y) => x >= 0 && y >= 0 && x < size && y < size;
    const neighbors = (x, y) => [[1, 0], [-1, 0], [0, 1], [0, -1]].map(([dx, dy]) => [x + dx, y + dy]).filter(([nx, ny]) => inBounds(nx, ny));
    const count = (color) => state.board.filter((v) => v === color).length;
    const finish = () => { state.finished = true; const score = Math.max(1, count("black") * 10 + (count("black") > count("white") ? 200 : 0)); registerScore(api, score, state); api.status(`結束 · 黑 ${count("black")} / 白 ${count("white")}`); };
    const render = () => {
      boardEl.innerHTML = state.board.map((v, i) => `<button class="board-game-cell ${v}" type="button" data-i="${i}" aria-label="${i}">${v ? `<span></span>` : ""}</button>`).join("");
      if (!state.finished) api.status(`${state.turn === "black" ? "黑" : "白"}方走 · 黑 ${count("black")} / 白 ${count("white")}`);
    };
    const reversiFlips = (x, y, color) => {
      const other = color === "black" ? "white" : "black";
      const flips = [];
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
        const line = []; let nx = x + dx, ny = y + dy;
        while (inBounds(nx, ny) && state.board[idx(nx, ny)] === other) { line.push(idx(nx, ny)); nx += dx; ny += dy; }
        if (line.length && inBounds(nx, ny) && state.board[idx(nx, ny)] === color) flips.push(...line);
      }
      return flips;
    };
    const liberties = (start, color, seen = new Set()) => {
      const stack = [start], group = new Set(), libs = new Set();
      while (stack.length) {
        const current = stack.pop(); if (group.has(current)) continue; group.add(current);
        const x = current % size, y = Math.floor(current / size);
        for (const [nx, ny] of neighbors(x, y)) {
          const ni = idx(nx, ny), v = state.board[ni];
          if (!v) libs.add(ni); else if (v === color && !group.has(ni) && !seen.has(ni)) stack.push(ni);
        }
      }
      return { group, libs };
    };
    const gomokuWin = (x, y, color) => [[1, 0], [0, 1], [1, 1], [1, -1]].some(([dx, dy]) => {
      let total = 1;
      for (const sign of [1, -1]) { let nx = x + dx * sign, ny = y + dy * sign; while (inBounds(nx, ny) && state.board[idx(nx, ny)] === color) { total += 1; nx += dx * sign; ny += dy * sign; } }
      return total >= 5;
    });
    const play = (i) => {
      if (state.finished || state.board[i]) return;
      const x = i % size, y = Math.floor(i / size);
      if (isReversi) {
        const flips = reversiFlips(x, y, state.turn); if (!flips.length) return;
        state.board[i] = state.turn; flips.forEach((fi) => { state.board[fi] = state.turn; });
      } else {
        state.board[i] = state.turn;
        if (type === "go") {
          const other = state.turn === "black" ? "white" : "black";
          for (const [nx, ny] of neighbors(x, y)) if (state.board[idx(nx, ny)] === other) { const group = liberties(idx(nx, ny), other); if (!group.libs.size) group.group.forEach((gi) => { state.board[gi] = ""; }); }
        }
        if (type === "gomoku" && gomokuWin(x, y, state.turn)) { finish(); render(); return; }
      }
      state.passCount = 0;
      state.turn = state.turn === "black" ? "white" : "black";
      render();
    };
    const reset = () => {
      state.startedAt = Date.now(); state.board = Array(size * size).fill(""); state.turn = "black"; state.finished = false; state.passCount = 0;
      if (isReversi) { state.board[idx(3, 3)] = "white"; state.board[idx(4, 4)] = "white"; state.board[idx(3, 4)] = "black"; state.board[idx(4, 3)] = "black"; }
      render();
    };
    api.onAction = (action) => {
      if (action === "new") reset();
      if (action === "finish") finish();
      if (action === "pass" && !state.finished) { state.passCount += 1; state.turn = state.turn === "black" ? "white" : "black"; if (state.passCount >= 2) finish(); render(); }
    };
    api.root.onclick = (event) => { const btn = event.target.closest("[data-i]"); if (btn) play(Number(btn.dataset.i)); };
    reset();
  }

  window.mountHackmeInlineDiscGame = mountInlineDiscGame;
}());
