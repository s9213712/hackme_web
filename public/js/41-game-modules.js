'use strict';

(function () {
  const catalog = [
    { key: "chess", title: "西洋棋", subtitle: "玩家對戰 / 電腦練習", legacy: true },
    { key: "sudoku", title: "數獨", subtitle: "單人邏輯解題", legacy: true },
    { key: "minesweeper", title: "踩地雷", subtitle: "單人推理挑戰", legacy: true },
    { key: "1a2b", title: "1A2B", subtitle: "單人猜數字", legacy: true },
    { key: "tetris", title: "俄羅斯方塊", subtitle: "高分消除挑戰", legacy: true },
    { key: "space_shooter", title: "宇宙戰機", subtitle: "高分射擊挑戰", legacy: true },
    { key: "fps_arena", title: "3D 射擊場", subtitle: "四模式 3D 射擊訓練", legacy: true },
    { key: "snake", title: "貪食蛇", subtitle: "滑動或方向鍵控制蛇吃食物" },
    { key: "game_2048", title: "2048", subtitle: "合併數字方塊，挑戰最高分" },
    { key: "brick_breaker", title: "打磚塊", subtitle: "移動擋板反彈球打掉磚塊" },
    { key: "reversi", title: "黑白棋", subtitle: "本機雙人輪流翻子" },
    { key: "go", title: "圍棋", subtitle: "9 路簡化圍棋，本機雙人" },
    { key: "gomoku", title: "五子棋", subtitle: "15 路本機雙人，五子連線勝" },
  ];

  const modules = {};
  const byKey = (key) => catalog.find((game) => game.key === key) || catalog[0];
  const cell = (value, cls = "") => `<button class="${cls}" type="button">${value || ""}</button>`;
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  function makeCtx(api, title) {
    api.setTitle(title);
    api.setActions(`<button class="btn game-mini-btn btn-primary" type="button" data-action="new">開始</button>`);
  }

  function registerScore(api, score, state, difficulty = "standard") {
    if (!score || score <= 0) return;
    api.submitScore({
      score,
      difficulty,
      puzzle_id: api.key,
      raw_elapsed_ms: Math.max(1, Date.now() - state.startedAt),
      elapsed_ms: Math.max(1, Date.now() - state.startedAt),
      penalty_seconds: 0,
      guess_count: 0,
    });
  }

  modules.snake = {
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
  };

  modules.game_2048 = {
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
  };

  modules.brick_breaker = {
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
  };

  function mountDiscGame(api, type) {
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

  modules.reversi = { mount: (api) => mountDiscGame(api, "reversi") };
  modules.go = { mount: (api) => mountDiscGame(api, "go") };
  modules.gomoku = { mount: (api) => mountDiscGame(api, "gomoku") };

  window.HACKME_GAME_CATALOG = catalog;
  window.HACKME_GAME_MODULES = modules;
  window.hackmeGameByKey = byKey;
}());
