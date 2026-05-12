'use strict';

(function () {
  const { makeCtx, registerScore } = window.HACKME_LOCAL_GAME_HELPERS;
window.registerHackmeLocalGameModule("snake", {
    mount(api) {
      makeCtx(api, "貪食蛇");
      const size = 18;
      const state = { startedAt: Date.now(), dir: [1, 0], next: [1, 0], snake: [], food: [8, 8], score: 0, timer: null, over: true };
      api.root.innerHTML = `<canvas class="arcade-canvas" width="360" height="360" aria-label="貪食蛇"></canvas>`;
      api.setControls(["左", "上", "下", "右"].map((t) => `<button class="btn game-mini-btn" data-dir="${t}">${t}</button>`).join(""));
      const canvas = api.root.querySelector("canvas");
      const ctx = canvas.getContext("2d");
      const draw = () => {
        ctx.fillStyle = "#07111f"; ctx.fillRect(0, 0, 360, 360);
        ctx.fillStyle = "#22c55e";
        state.snake.forEach(([x, y], i) => { ctx.fillStyle = i ? "#16a34a" : "#86efac"; ctx.fillRect(x * 20 + 2, y * 20 + 2, 16, 16); });
        ctx.fillStyle = "#f97316"; ctx.fillRect(state.food[0] * 20 + 3, state.food[1] * 20 + 3, 14, 14);
      };
      const placeFood = () => {
        do state.food = [Math.floor(Math.random() * size), Math.floor(Math.random() * size)];
        while (state.snake.some(([x, y]) => x === state.food[0] && y === state.food[1]));
      };
      const tick = () => {
        state.dir = state.next;
        const head = state.snake[0];
        const next = [head[0] + state.dir[0], head[1] + state.dir[1]];
        if (next[0] < 0 || next[1] < 0 || next[0] >= size || next[1] >= size || state.snake.some(([x, y]) => x === next[0] && y === next[1])) {
          state.over = true; clearInterval(state.timer); registerScore(api, state.score, state); api.status(`結束 · 分數 ${state.score}`); return;
        }
        state.snake.unshift(next);
        if (next[0] === state.food[0] && next[1] === state.food[1]) { state.score += 10; placeFood(); }
        else state.snake.pop();
        api.status(`分數 ${state.score} · 長度 ${state.snake.length}`);
        draw();
      };
      const start = () => { clearInterval(state.timer); Object.assign(state, { startedAt: Date.now(), dir: [1, 0], next: [1, 0], snake: [[5, 9], [4, 9], [3, 9]], score: 0, over: false }); placeFood(); draw(); state.timer = setInterval(tick, 135); };
      const move = (name) => {
        const map = { "左": [-1, 0], "右": [1, 0], "上": [0, -1], "下": [0, 1] };
        const dir = map[name]; if (!dir) return;
        if (dir[0] + state.dir[0] || dir[1] + state.dir[1]) state.next = dir;
      };
      api.onAction = (action) => { if (action === "new") start(); };
      api.onControl = (target) => move(target.dataset.dir);
      api.onKey = (event) => {
        if (event.key === "ArrowLeft") move("左");
        if (event.key === "ArrowRight") move("右");
        if (event.key === "ArrowUp") move("上");
        if (event.key === "ArrowDown") move("下");
      };
      start();
      return () => clearInterval(state.timer);
    },
  });
}());
