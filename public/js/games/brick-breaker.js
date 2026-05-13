'use strict';

(function () {
  const { makeCtx, registerScore, clamp } = window.HACKME_LOCAL_GAME_HELPERS;
window.registerHackmeLocalGameModule("brick_breaker", {
    mount(api) {
      makeCtx(api, "打磚塊");
      api.setSwipeMode?.("hold");
      const state = { startedAt: 0, score: 0, lives: 3, x: 180, balls: [[180, 280, 0, 0]], bricks: [], left: false, right: false, timer: null, over: false, multiball: 0, boss: 0, dailyChallenge: null };
      api.root.innerHTML = `<canvas class="arcade-canvas tall" width="360" height="480" aria-label="打磚塊"></canvas>`;
      api.setControls(`<button class="btn game-mini-btn" data-hold="left">左</button><button class="btn game-mini-btn btn-primary" data-action="new">重開</button><button class="btn game-mini-btn" data-hold="right">右</button>`);
      const canvas = api.root.querySelector("canvas"), ctx = canvas.getContext("2d");
      const resetBricks = () => {
        state.bricks = [];
        for (let y = 0; y < 5; y += 1) for (let x = 0; x < 8; x += 1) {
          const boss = y === 0 && x === 3;
          const shield = y === 1 && x % 3 === 0;
          state.bricks.push({ x: 16 + x * 41, y: 42 + y * 22, w: 34, h: 14, on: true, hp: boss ? 5 : shield ? 2 : 1, boss, shield });
        }
      };
      const draw = () => {
        ctx.fillStyle = "#07111f"; ctx.fillRect(0, 0, 360, 480);
        state.bricks.forEach((b) => { if (b.on) { ctx.fillStyle = b.boss ? "#f97316" : b.shield ? "#a78bfa" : "#38bdf8"; ctx.fillRect(b.x, b.y, b.w, b.h); if (b.hp > 1) { ctx.fillStyle = "#0f172a"; ctx.fillRect(b.x + 4, b.y + 5, b.w - 8, 3); } } });
        ctx.fillStyle = "#e5e7eb"; ctx.fillRect(state.x - 42, 444, 84, 10);
        state.balls.forEach((ball) => { ctx.beginPath(); ctx.arc(ball[0], ball[1], 7, 0, Math.PI * 2); ctx.fillStyle = "#facc15"; ctx.fill(); });
      };
      const drawGameOver = () => {
        ctx.fillStyle = "rgba(7,17,31,.78)";
        ctx.fillRect(42, 184, 276, 112);
        ctx.textAlign = "center";
        ctx.fillStyle = "#ff4f6d";
        ctx.font = "700 28px system-ui, sans-serif";
        ctx.fillText("GAME OVER", 180, 226);
        ctx.fillStyle = "rgba(226,232,240,.9)";
        ctx.font = "13px system-ui, sans-serif";
        ctx.fillText(`分數 ${Number(state.score || 0).toLocaleString()} · Boss 磚 ${state.boss || 0}`, 180, 254);
        ctx.textAlign = "start";
      };
      const finish = () => {
        if (state.over) return;
        state.over = true;
        clearInterval(state.timer);
        state.timer = null;
        state.balls = [];
        draw();
        drawGameOver();
        registerScore(api, state.score, state, state.dailyChallenge?.difficulty || "standard");
        api.status(`遊戲結束 · 分數 ${state.score} · Boss 磚 ${state.boss || 0}`);
      };
      const triggerMultiball = () => {
        if (state.balls.length >= 3) return;
        const base = state.balls[0] || [state.x, 320, 3, -4];
        state.balls.push([base[0], base[1], -Math.abs(base[2]) - 1, -4.5], [base[0], base[1], Math.abs(base[2]) + 1, -4.2]);
        state.multiball += 1;
        api.achievement?.("multiball", "多球開局", "啟動多球。");
        api.mission?.("multiball", state.multiball, 1, "啟動多球");
      };
      const tick = () => {
        if (state.left) state.x -= 6; if (state.right) state.x += 6; state.x = clamp(state.x, 44, 316);
        state.balls.forEach((ball) => {
          ball[0] += ball[2]; ball[1] += ball[3];
          if (ball[0] < 8 || ball[0] > 352) ball[2] *= -1;
          if (ball[1] < 8) ball[3] *= -1;
          if (ball[1] > 438 && Math.abs(ball[0] - state.x) < 50) { ball[3] = -Math.abs(ball[3]); ball[2] += (ball[0] - state.x) * 0.04; }
          for (const b of state.bricks) if (b.on && ball[0] > b.x && ball[0] < b.x + b.w && ball[1] > b.y && ball[1] < b.y + b.h) {
            b.hp -= 1; ball[3] *= -1; state.score += b.boss ? 40 : 25;
            if (b.hp <= 0) {
              b.on = false;
              if (b.boss) { state.boss += 1; triggerMultiball(); api.achievement?.("boss-brick", "Boss 磚擊破", "擊破 Boss 磚。"); api.mission?.("boss", state.boss, 1, "擊破 Boss 磚"); }
            }
            break;
          }
        });
        state.balls = state.balls.filter((ball) => ball[1] <= 490);
        if (!state.balls.length) {
          state.lives -= 1;
          if (state.lives <= 0) {
            finish();
            return;
          }
          state.balls = [[state.x, 320, 3, -4]];
        }
        if (state.bricks.every((b) => !b.on)) { state.score += 500; resetBricks(); }
        api.status(`分數 ${state.score} · 生命 ${state.lives} · 球 ${state.balls.length}`);
        draw();
      };
      const start = () => { clearInterval(state.timer); Object.assign(state, { startedAt: Date.now(), score: 0, lives: 3, x: 180, balls: [[180, 280, 3, -4]], left: false, right: false, over: false, multiball: 0, boss: 0, dailyChallenge: api.dailyChallenge?.() || null }); resetBricks(); state.timer = setInterval(tick, 16); };
      api.onAction = (action) => { if (action === "new") start(); };
      api.onControl = (target, pressed) => { if (target.dataset.hold === "left") state.left = pressed; if (target.dataset.hold === "right") state.right = pressed; };
      api.onKey = (event, pressed) => { if (event.key === "ArrowLeft") state.left = pressed; if (event.key === "ArrowRight") state.right = pressed; };
      resetBricks();
      draw();
      api.status("待機 · 按開始後才會發球、計時與送成績。");
      return () => clearInterval(state.timer);
    },
  });
}());
