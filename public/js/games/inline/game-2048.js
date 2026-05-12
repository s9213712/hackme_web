'use strict';

(function () {
  const { makeCtx, registerScore, cell } = window.HACKME_INLINE_GAME_HELPERS;
window.registerHackmeInlineGameModule("game_2048", {
    mount(api) {
      makeCtx(api, "2048");
      const state = { startedAt: Date.now(), board: [], score: 0 };
      api.root.innerHTML = `<div class="game-2048-board" aria-label="2048"></div>`;
      api.setControls(["左", "上", "下", "右"].map((t) => `<button class="btn game-mini-btn" data-dir="${t}">${t}</button>`).join(""));
      const root = api.root.querySelector(".game-2048-board");
      const emptyCells = () => state.board.flatMap((row, y) => row.map((v, x) => v ? null : [x, y])).filter(Boolean);
      const addTile = () => { const cells = emptyCells(); if (!cells.length) return; const [x, y] = cells[Math.floor(Math.random() * cells.length)]; state.board[y][x] = Math.random() > 0.9 ? 4 : 2; };
      const render = () => { root.innerHTML = state.board.flat().map((v) => cell(v, `tile-${v || 0}`)).join(""); api.status(`分數 ${state.score}`); };
      const reset = () => { state.startedAt = Date.now(); state.score = 0; state.board = Array.from({ length: 4 }, () => Array(4).fill(0)); addTile(); addTile(); render(); };
      const merge = (line) => {
        const values = line.filter(Boolean);
        for (let i = 0; i < values.length - 1; i += 1) if (values[i] === values[i + 1]) { values[i] *= 2; state.score += values[i]; values.splice(i + 1, 1); }
        while (values.length < 4) values.push(0);
        return values;
      };
      const move = (dir) => {
        const before = JSON.stringify(state.board);
        for (let i = 0; i < 4; i += 1) {
          let line = dir === "左" || dir === "右" ? state.board[i].slice() : state.board.map((row) => row[i]);
          if (dir === "右" || dir === "下") line.reverse();
          line = merge(line);
          if (dir === "右" || dir === "下") line.reverse();
          for (let j = 0; j < 4; j += 1) if (dir === "左" || dir === "右") state.board[i][j] = line[j]; else state.board[j][i] = line[j];
        }
        if (before !== JSON.stringify(state.board)) addTile();
        render();
        if (!emptyCells().length && before === JSON.stringify(state.board)) { registerScore(api, state.score, state); api.status(`無可移動 · 分數 ${state.score}`); }
      };
      api.onAction = (action) => { if (action === "new") reset(); };
      api.onControl = (target) => move(target.dataset.dir);
      api.onKey = (event) => ({ ArrowLeft: "左", ArrowRight: "右", ArrowUp: "上", ArrowDown: "下" }[event.key] && move({ ArrowLeft: "左", ArrowRight: "右", ArrowUp: "上", ArrowDown: "下" }[event.key]));
      reset();
    },
  });
}());
