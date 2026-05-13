'use strict';

(function () {
  const { makeCtx, registerScore } = window.HACKME_LOCAL_GAME_HELPERS;
window.registerHackmeLocalGameModule("snake", {
    mount(api) {
      makeCtx(api, "貪食蛇");
      const size = 18;
      const state = { startedAt: 0, dir: [1, 0], next: [1, 0], snake: [], food: [8, 8], powerup: [12, 6], obstacles: [], score: 0, timer: null, over: true, maxLength: 0, powerupsCollected: 0, speedZoneTouched: false, dailyChallenge: null };
      api.root.innerHTML = `<canvas class="arcade-canvas" width="360" height="360" aria-label="貪食蛇"></canvas>`;
      api.setControls(["左", "上", "下", "右"].map((t) => `<button class="btn game-mini-btn" data-dir="${t}">${t}</button>`).join(""));
      const canvas = api.root.querySelector("canvas");
      const ctx = canvas.getContext("2d");
      const draw = () => {
        ctx.fillStyle = "#07111f"; ctx.fillRect(0, 0, 360, 360);
        ctx.fillStyle = "#22c55e";
        ctx.fillStyle = "rgba(56,189,248,.18)"; ctx.fillRect(2 * 20, 2 * 20, 5 * 20, 3 * 20);
        ctx.fillStyle = "#64748b";
        state.obstacles.forEach(([x, y]) => { ctx.fillRect(x * 20 + 2, y * 20 + 2, 16, 16); });
        ctx.fillStyle = "#22c55e";
        state.snake.forEach(([x, y], i) => { ctx.fillStyle = i ? "#16a34a" : "#86efac"; ctx.fillRect(x * 20 + 2, y * 20 + 2, 16, 16); });
        ctx.fillStyle = "#f97316"; ctx.fillRect(state.food[0] * 20 + 3, state.food[1] * 20 + 3, 14, 14);
        ctx.fillStyle = "#facc15"; ctx.beginPath(); ctx.arc(state.powerup[0] * 20 + 10, state.powerup[1] * 20 + 10, 7, 0, Math.PI * 2); ctx.fill();
      };
      const drawGameOver = () => {
        ctx.fillStyle = "rgba(7,17,31,.78)";
        ctx.fillRect(38, 126, 284, 108);
        ctx.textAlign = "center";
        ctx.fillStyle = "#ff4f6d";
        ctx.font = "700 28px system-ui, sans-serif";
        ctx.fillText("GAME OVER", 180, 170);
        ctx.fillStyle = "rgba(226,232,240,.9)";
        ctx.font = "13px system-ui, sans-serif";
        ctx.fillText(`分數 ${Number(state.score || 0).toLocaleString()} · 長度 ${state.maxLength || 0}`, 180, 198);
        ctx.textAlign = "start";
      };
      const blocked = ([x, y]) => state.snake.some(([sx, sy]) => sx === x && sy === y) || state.obstacles.some(([ox, oy]) => ox === x && oy === y);
      const placeFood = () => {
        do state.food = [Math.floor(Math.random() * size), Math.floor(Math.random() * size)];
        while (blocked(state.food));
      };
      const placePowerup = () => {
        do state.powerup = [Math.floor(Math.random() * size), Math.floor(Math.random() * size)];
        while (blocked(state.powerup) || (state.food[0] === state.powerup[0] && state.food[1] === state.powerup[1]));
      };
      const tick = () => {
        state.dir = state.next;
        const head = state.snake[0];
        const next = [head[0] + state.dir[0], head[1] + state.dir[1]];
        if (next[0] < 0 || next[1] < 0 || next[0] >= size || next[1] >= size || state.snake.some(([x, y]) => x === next[0] && y === next[1]) || state.obstacles.some(([x, y]) => x === next[0] && y === next[1])) {
          state.over = true;
          clearInterval(state.timer);
          state.timer = null;
          draw();
          drawGameOver();
          registerScore(api, state.score, state, state.dailyChallenge?.difficulty || "standard");
          api.status(`遊戲結束 · 分數 ${state.score} · 最高長度 ${state.maxLength || state.snake.length}`);
          return;
        }
        state.snake.unshift(next);
        if (next[0] === state.food[0] && next[1] === state.food[1]) { state.score += 10; placeFood(); }
        else if (next[0] === state.powerup[0] && next[1] === state.powerup[1]) {
          state.score += 50;
          state.powerupsCollected += 1;
          api.achievement?.("powerup", "道具吞食", "吃到任務道具。");
          api.mission?.("powerup", state.powerupsCollected, 1, "吃到道具");
          placePowerup();
        }
        else state.snake.pop();
        state.maxLength = Math.max(state.maxLength, state.snake.length);
        if (state.maxLength >= 12) api.achievement?.("long-snake", "長蛇成形", "長度達 12。");
        if (next[0] >= 2 && next[0] <= 6 && next[1] >= 2 && next[1] <= 4) {
          state.score += 1;
          if (!state.speedZoneTouched) {
            state.speedZoneTouched = true;
            api.achievement?.("speed-zone", "加速區生還", "穿越加速區後繼續得分。");
          }
        }
        api.status(`分數 ${state.score} · 長度 ${state.snake.length} · 道具 ${state.powerupsCollected}`);
        draw();
      };
      const start = () => {
        clearInterval(state.timer);
        Object.assign(state, { startedAt: Date.now(), dir: [1, 0], next: [1, 0], snake: [[5, 9], [4, 9], [3, 9]], score: 0, over: false, maxLength: 3, powerupsCollected: 0, speedZoneTouched: false, dailyChallenge: api.dailyChallenge?.() || null });
        state.obstacles = [[9, 7], [10, 7], [11, 7], [7, 12], [7, 13], [13, 4], [14, 4]];
        placeFood(); placePowerup(); draw(); state.timer = setInterval(tick, 120);
      };
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
      state.obstacles = [[9, 7], [10, 7], [11, 7], [7, 12], [7, 13], [13, 4], [14, 4]];
      draw();
      api.status("待機 · 按開始後才會計時與移動。");
      return () => clearInterval(state.timer);
    },
  });
}());
