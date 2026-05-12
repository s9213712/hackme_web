'use strict';

(function () {
  const { makeCtx, registerScore, clamp } = window.HACKME_INLINE_GAME_HELPERS;
window.registerHackmeInlineGameModule("brick_breaker", {
    mount(api) {
      makeCtx(api, "打磚塊");
      const state = { startedAt: Date.now(), score: 0, lives: 3, x: 180, ball: [180, 280, 3, -4], bricks: [], left: false, right: false, timer: null };
      api.root.innerHTML = `<canvas class="arcade-canvas tall" width="360" height="480" aria-label="打磚塊"></canvas>`;
      api.setControls(`<button class="btn game-mini-btn" data-hold="left">左</button><button class="btn game-mini-btn btn-primary" data-action="new">重開</button><button class="btn game-mini-btn" data-hold="right">右</button>`);
      const canvas = api.root.querySelector("canvas"), ctx = canvas.getContext("2d");
      const resetBricks = () => { state.bricks = []; for (let y = 0; y < 5; y += 1) for (let x = 0; x < 8; x += 1) state.bricks.push({ x: 16 + x * 41, y: 42 + y * 22, w: 34, h: 14, on: true }); };
      const draw = () => {
        ctx.fillStyle = "#07111f"; ctx.fillRect(0, 0, 360, 480);
        state.bricks.forEach((b) => { if (b.on) { ctx.fillStyle = "#38bdf8"; ctx.fillRect(b.x, b.y, b.w, b.h); } });
        ctx.fillStyle = "#e5e7eb"; ctx.fillRect(state.x - 42, 444, 84, 10);
        ctx.beginPath(); ctx.arc(state.ball[0], state.ball[1], 7, 0, Math.PI * 2); ctx.fillStyle = "#facc15"; ctx.fill();
      };
      const tick = () => {
        if (state.left) state.x -= 6; if (state.right) state.x += 6; state.x = clamp(state.x, 44, 316);
        state.ball[0] += state.ball[2]; state.ball[1] += state.ball[3];
        if (state.ball[0] < 8 || state.ball[0] > 352) state.ball[2] *= -1;
        if (state.ball[1] < 8) state.ball[3] *= -1;
        if (state.ball[1] > 438 && Math.abs(state.ball[0] - state.x) < 50) { state.ball[3] = -Math.abs(state.ball[3]); state.ball[2] += (state.ball[0] - state.x) * 0.04; }
        for (const b of state.bricks) if (b.on && state.ball[0] > b.x && state.ball[0] < b.x + b.w && state.ball[1] > b.y && state.ball[1] < b.y + b.h) { b.on = false; state.ball[3] *= -1; state.score += 25; break; }
        if (state.ball[1] > 490) { state.lives -= 1; state.ball = [state.x, 320, 3, -4]; if (state.lives <= 0) { clearInterval(state.timer); registerScore(api, state.score, state); } }
        if (state.bricks.every((b) => !b.on)) { state.score += 500; resetBricks(); }
        api.status(`分數 ${state.score} · 生命 ${state.lives}`);
        draw();
      };
      const start = () => { clearInterval(state.timer); Object.assign(state, { startedAt: Date.now(), score: 0, lives: 3, x: 180, ball: [180, 280, 3, -4], left: false, right: false }); resetBricks(); state.timer = setInterval(tick, 16); };
      api.onAction = (action) => { if (action === "new") start(); };
      api.onControl = (target, pressed) => { if (target.dataset.hold === "left") state.left = pressed; if (target.dataset.hold === "right") state.right = pressed; };
      api.onKey = (event, pressed) => { if (event.key === "ArrowLeft") state.left = pressed; if (event.key === "ArrowRight") state.right = pressed; };
      start();
      return () => clearInterval(state.timer);
    },
  });
}());
