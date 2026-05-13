'use strict';

(function () {
  const { makeCtx, registerScore, cell } = window.HACKME_LOCAL_GAME_HELPERS;
window.registerHackmeLocalGameModule("game_2048", {
    mount(api) {
      makeCtx(api, "2048");
      const state = { startedAt: 0, board: Array.from({ length: 4 }, () => Array(4).fill(0)), score: 0, mode: "classic", moves: 0, moveLimit: 60, history: [], maxTile: 0, active: false, finished: false, dailyChallenge: null };
      const setActions = () => api.setActions(`
        <button class="btn game-mini-btn btn-primary" type="button" data-action="new">開始</button>
        <button class="btn game-mini-btn" type="button" data-action="mode">模式：${state.mode === "classic" ? "一般" : state.mode === "obstacle" ? "障礙" : "限步"}</button>
        <button class="btn game-mini-btn" type="button" data-action="undo">撤銷 ${Math.max(0, 3 - state.history.length)}</button>
      `);
      api.root.innerHTML = `<div class="game-2048-board" aria-label="2048"></div>`;
      api.setControls(["左", "上", "下", "右"].map((t) => `<button class="btn game-mini-btn" data-dir="${t}">${t}</button>`).join(""));
      const root = api.root.querySelector(".game-2048-board");
      const emptyCells = () => state.board.flatMap((row, y) => row.map((v, x) => v ? null : [x, y])).filter(Boolean);
      const addTile = () => { const cells = emptyCells(); if (!cells.length) return; const [x, y] = cells[Math.floor(Math.random() * cells.length)]; state.board[y][x] = Math.random() > 0.9 ? 4 : 2; };
      const placeObstacles = () => {
        if (state.mode !== "obstacle") return;
        [[1, 1], [2, 2]].forEach(([x, y]) => { state.board[y][x] = -1; });
      };
      const render = () => {
        const cells = state.board.flat().map((v) => cell(v < 0 ? "X" : v, v < 0 ? "tile-block" : `tile-${v || 0}`)).join("");
        const overlay = state.finished
          ? `<div class="single-game-over-overlay">GAME OVER<br><small>分數 ${Number(state.score || 0).toLocaleString()} · 最大 ${state.maxTile || 0} · 步數 ${state.moves}</small></div>`
          : "";
        root.innerHTML = cells + overlay;
        if (state.finished) api.status(`遊戲結束 · 分數 ${state.score} · 最大 ${state.maxTile || 0} · 步數 ${state.moves}`);
        else if (state.active) api.status(`分數 ${state.score} · 最大 ${state.maxTile || 0} · 步數 ${state.moves}${state.mode === "limited" ? `/${state.moveLimit}` : ""}`);
        else api.status(`待機 · 模式：${state.mode === "classic" ? "一般" : state.mode === "obstacle" ? "障礙" : "限步"} · 按開始後才會產生初始方塊。`);
        setActions();
      };
      const reset = () => {
        state.startedAt = Date.now(); state.score = 0; state.moves = 0; state.maxTile = 0; state.history = []; state.active = true; state.finished = false; state.dailyChallenge = api.dailyChallenge?.() || null;
        state.board = Array.from({ length: 4 }, () => Array(4).fill(0));
        placeObstacles(); addTile(); addTile(); render();
      };
      const merge = (line) => {
        const values = line.filter((value) => value > 0);
        for (let i = 0; i < values.length - 1; i += 1) if (values[i] === values[i + 1]) { values[i] *= 2; state.score += values[i]; values.splice(i + 1, 1); }
        while (values.length < 4) values.push(0);
        return values;
      };
      const mergeLineWithBlocks = (line) => {
        const output = [];
        for (let i = 0; i < line.length;) {
          if (line[i] === -1) { output.push(-1); i += 1; continue; }
          const segment = [];
          while (i < line.length && line[i] !== -1) { segment.push(line[i]); i += 1; }
          const values = segment.filter((value) => value > 0);
          for (let j = 0; j < values.length - 1; j += 1) {
            if (values[j] === values[j + 1]) {
              values[j] *= 2;
              state.score += values[j];
              state.maxTile = Math.max(state.maxTile, values[j]);
              values.splice(j + 1, 1);
            }
          }
          while (values.length < segment.length) values.push(0);
          output.push(...values);
        }
        return output;
      };
      const canMove = () => {
        if (emptyCells().length) return true;
        for (let y = 0; y < 4; y += 1) for (let x = 0; x < 4; x += 1) {
          const value = state.board[y][x];
          if (value <= 0) continue;
          if (x < 3 && state.board[y][x + 1] === value) return true;
          if (y < 3 && state.board[y + 1][x] === value) return true;
        }
        return false;
      };
      const move = (dir) => {
        if (!state.active) return;
        const before = JSON.stringify(state.board);
        const beforeScore = state.score;
        for (let i = 0; i < 4; i += 1) {
          let line = dir === "左" || dir === "右" ? state.board[i].slice() : state.board.map((row) => row[i]);
          if (dir === "右" || dir === "下") line.reverse();
          line = state.mode === "obstacle" ? mergeLineWithBlocks(line) : merge(line);
          if (dir === "右" || dir === "下") line.reverse();
          for (let j = 0; j < 4; j += 1) if (dir === "左" || dir === "右") state.board[i][j] = line[j]; else state.board[j][i] = line[j];
        }
        if (before !== JSON.stringify(state.board)) {
          if (state.history.length < 3) state.history.push({ board: JSON.parse(before), score: beforeScore, moves: state.moves, maxTile: state.maxTile });
          state.moves += 1;
          addTile();
        }
        render();
        if (state.maxTile >= 512) { api.achievement?.("tile-512", "512 里程碑", "合成 512。"); api.mission?.("tile-512", state.maxTile, 512, "合出 512"); }
        if (state.mode === "limited") api.mission?.("limited", state.moves, state.moveLimit, "限步模式完成 60 步");
        if ((state.mode === "limited" && state.moves >= state.moveLimit) || !canMove()) {
          state.active = false;
          state.finished = true;
          registerScore(api, state.score, state, state.dailyChallenge?.difficulty || "standard");
          render();
        }
      };
      const undo = () => {
        if (!state.active) return;
        const row = state.history.pop();
        if (!row) return;
        state.board = row.board;
        state.score = row.score;
        state.moves = row.moves;
        state.maxTile = row.maxTile;
        api.achievement?.("undo-used", "戰術撤銷", "使用撤銷仍繼續挑戰。");
        render();
      };
      api.onAction = (action) => {
        if (action === "new") reset();
        if (action === "mode") {
          state.mode = state.mode === "classic" ? "obstacle" : state.mode === "obstacle" ? "limited" : "classic";
          if (state.active) reset();
          else render();
        }
        if (action === "undo") undo();
      };
      api.onControl = (target) => move(target.dataset.dir);
      api.onKey = (event) => ({ ArrowLeft: "左", ArrowRight: "右", ArrowUp: "上", ArrowDown: "下" }[event.key] && move({ ArrowLeft: "左", ArrowRight: "右", ArrowUp: "上", ArrowDown: "下" }[event.key]));
      render();
    },
  });
}());
