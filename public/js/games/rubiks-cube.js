'use strict';

(function () {
  const { makeCtx, registerScore } = window.HACKME_LOCAL_GAME_HELPERS;
  const FACE_NAMES = ["U", "R", "F", "D", "L", "B"];
  const FACE_LABELS = { U: "上", D: "下", F: "前", B: "後", R: "右", L: "左" };
  const FACE_COLORS = {
    U: "#f8fafc",
    D: "#facc15",
    F: "#22c55e",
    B: "#3b82f6",
    R: "#ef4444",
    L: "#f97316",
  };
  const FACE_NORMALS = {
    U: [0, 1, 0],
    D: [0, -1, 0],
    F: [0, 0, 1],
    B: [0, 0, -1],
    R: [1, 0, 0],
    L: [-1, 0, 0],
  };
  const FACE_AXES = {
    U: ["y", 1, -1],
    D: ["y", -1, 1],
    F: ["z", 1, -1],
    B: ["z", -1, 1],
    R: ["x", 1, -1],
    L: ["x", -1, 1],
  };
  const inverseMove = (move) => move.endsWith("'") ? move.slice(0, -1) : `${move}'`;

  function sameVec(a, b) {
    return a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
  }

  function rotateVec(vec, axis, sign) {
    const [x, y, z] = vec;
    if (axis === "x") return sign > 0 ? [x, -z, y] : [x, z, -y];
    if (axis === "y") return sign > 0 ? [z, y, -x] : [-z, y, x];
    return sign > 0 ? [-y, x, z] : [y, -x, z];
  }

  function createSolvedCube() {
    const cube = [];
    for (let x = -1; x <= 1; x += 1) {
      for (let y = -1; y <= 1; y += 1) {
        for (let z = -1; z <= 1; z += 1) {
          if (x === 0 && y === 0 && z === 0) continue;
          const stickers = [];
          if (y === 1) stickers.push({ dir: [0, 1, 0], face: "U" });
          if (y === -1) stickers.push({ dir: [0, -1, 0], face: "D" });
          if (z === 1) stickers.push({ dir: [0, 0, 1], face: "F" });
          if (z === -1) stickers.push({ dir: [0, 0, -1], face: "B" });
          if (x === 1) stickers.push({ dir: [1, 0, 0], face: "R" });
          if (x === -1) stickers.push({ dir: [-1, 0, 0], face: "L" });
          cube.push({ pos: [x, y, z], stickers });
        }
      }
    }
    return cube;
  }

  function moveCube(cube, move) {
    const face = String(move || "")[0];
    const axisSpec = FACE_AXES[face];
    if (!axisSpec) return;
    const prime = String(move || "").endsWith("'");
    const [axis, layer, baseSign] = axisSpec;
    const sign = prime ? -baseSign : baseSign;
    const axisIndex = axis === "x" ? 0 : axis === "y" ? 1 : 2;
    cube.forEach((cubie) => {
      if (cubie.pos[axisIndex] !== layer) return;
      cubie.pos = rotateVec(cubie.pos, axis, sign);
      cubie.stickers.forEach((sticker) => {
        sticker.dir = rotateVec(sticker.dir, axis, sign);
      });
    });
  }

  function faceGrid(cube, face) {
    const normal = FACE_NORMALS[face];
    const grid = Array.from({ length: 9 }, () => "");
    cube.forEach((cubie) => {
      const sticker = cubie.stickers.find((item) => sameVec(item.dir, normal));
      if (!sticker) return;
      const [x, y, z] = cubie.pos;
      let row = 0;
      let col = 0;
      if (face === "F") { row = 1 - y; col = x + 1; }
      if (face === "B") { row = 1 - y; col = 1 - x; }
      if (face === "R") { row = 1 - y; col = 1 - z; }
      if (face === "L") { row = 1 - y; col = z + 1; }
      if (face === "U") { row = z + 1; col = x + 1; }
      if (face === "D") { row = 1 - z; col = x + 1; }
      grid[row * 3 + col] = sticker.face;
    });
    return grid;
  }

  function isSolved(cube) {
    return FACE_NAMES.every((face) => {
      const grid = faceGrid(cube, face);
      return grid.every((value) => value === face);
    });
  }

  function cancelSolutionStack(stack, move) {
    const inverse = inverseMove(move);
    if (stack[stack.length - 1] === inverse) stack.pop();
    else stack.push(inverse);
  }

  function scoreFor(state) {
    const elapsedSeconds = Math.floor((Date.now() - state.startedAt) / 1000);
    return Math.max(100, Math.round(6000 - state.moves * 85 - elapsedSeconds * 4 + Math.max(0, state.scrambleLength - 20) * 25));
  }

  window.registerHackmeLocalGameModule("rubiks_cube", {
    mount(api) {
      makeCtx(api, "3D 魔術方塊");
      const state = {
        cube: createSolvedCube(),
        active: false,
        solved: true,
        startedAt: 0,
        moves: 0,
        score: 0,
        scrambleLength: 24,
        solutionStack: [],
        viewX: -27,
        viewY: -34,
        drag: null,
        dailyChallenge: null,
      };

      api.root.innerHTML = `
        <div class="rubiks-game-shell">
          <div class="rubiks-stage" tabindex="0" aria-label="3D 魔術方塊，可拖曳旋轉視角">
            <div class="rubiks-cube-3d" aria-hidden="true"></div>
          </div>
          <div class="rubiks-side-panel">
            <div class="rubiks-chip"><strong>目標</strong><span>用六面轉動把每面恢復同色。</span></div>
            <div class="rubiks-chip"><strong>操作</strong><span>鍵盤 U/D/F/B/R/L，Shift 為反向；拖曳可轉視角。</span></div>
            <div class="rubiks-next-hint" id="rubiks-next-hint">按「打亂」開始。</div>
          </div>
        </div>
      `;
      const stage = api.root.querySelector(".rubiks-stage");
      const cubeEl = api.root.querySelector(".rubiks-cube-3d");
      const hintEl = api.root.querySelector("#rubiks-next-hint");

      const renderActions = () => api.setActions(`
        <button class="btn game-mini-btn btn-primary" type="button" data-action="new">打亂</button>
        <button class="btn game-mini-btn" type="button" data-action="hint">提示</button>
        <button class="btn game-mini-btn" type="button" data-action="solve">自動還原</button>
        <button class="btn game-mini-btn" type="button" data-action="reset">重置</button>
      `);
      const renderControls = () => {
        const moves = ["U", "U'", "D", "D'", "F", "F'", "B", "B'", "R", "R'", "L", "L'"];
        api.setControls(`
          <div class="rubiks-control-grid">
            ${moves.map((move) => `<button class="btn game-mini-btn" type="button" data-rubiks-move="${move}">${move}</button>`).join("")}
          </div>
          <div class="rubiks-view-controls">
            <button class="btn game-mini-btn" type="button" data-rubiks-view="left">視角左</button>
            <button class="btn game-mini-btn" type="button" data-rubiks-view="right">視角右</button>
            <button class="btn game-mini-btn" type="button" data-rubiks-view="up">視角上</button>
            <button class="btn game-mini-btn" type="button" data-rubiks-view="down">視角下</button>
          </div>
        `);
      };
      const statusText = () => {
        if (state.solved && state.active) return `完成 · ${state.moves} 步 · 分數 ${state.score}`;
        if (state.active) return `解題中 · ${state.moves} 步 · 剩餘提示 ${state.solutionStack.length}`;
        return state.solved ? "已還原 · 按打亂開始新題。" : `暫停 · ${state.moves} 步`;
      };
      const stickerMarkup = (face) => faceGrid(state.cube, face).map((value) => `
        <span class="rubiks-sticker" style="--rubiks-color:${FACE_COLORS[value] || "#111827"}" data-face="${value || ""}"></span>
      `).join("");
      const render = () => {
        cubeEl.style.transform = `rotateX(${state.viewX}deg) rotateY(${state.viewY}deg)`;
        cubeEl.innerHTML = FACE_NAMES.map((face) => `
          <div class="rubiks-face rubiks-face-${face}">
            <span class="rubiks-face-label">${FACE_LABELS[face]}</span>
            ${stickerMarkup(face)}
          </div>
        `).join("");
        api.status(statusText());
        renderActions();
        renderControls();
      };
      const finishIfSolved = () => {
        if (!state.active || !isSolved(state.cube)) return;
        state.active = false;
        state.solved = true;
        state.score = scoreFor(state);
        hintEl.textContent = `完成：${state.moves} 步，分數 ${state.score}。`;
        api.achievement?.("solve", "魔術方塊復原", "解開一顆 3D 魔術方塊。");
        api.mission?.("solve", 1, 1, "解開一顆 3D 魔術方塊");
        api.mission?.("under-40", state.moves <= 40 ? 40 : state.moves, 40, "40 步內復原");
        api.mission?.("under-3m", Date.now() - state.startedAt, 180000, "3 分鐘內復原");
        registerScore(api, state.score, state, state.dailyChallenge?.difficulty || "standard");
      };
      const applyMove = (move, options = {}) => {
        if (!move) return;
        moveCube(state.cube, move);
        if (!options.silent) {
          state.active = true;
          state.solved = false;
          state.moves += 1;
          cancelSolutionStack(state.solutionStack, move);
          hintEl.textContent = `剛轉動 ${move}，下一步可觀察邊角顏色。`;
          api.sound?.("uiClick", { volume: 0.08 });
        }
        render();
        finishIfSolved();
      };
      const scramble = () => {
        const moves = ["U", "D", "F", "B", "R", "L"];
        state.cube = createSolvedCube();
        state.solutionStack = [];
        state.moves = 0;
        state.score = 0;
        state.active = true;
        state.solved = false;
        state.startedAt = Date.now();
        state.dailyChallenge = api.dailyChallenge?.() || null;
        let previous = "";
        for (let i = 0; i < state.scrambleLength; i += 1) {
          let face = moves[Math.floor(Math.random() * moves.length)];
          while (face === previous) face = moves[Math.floor(Math.random() * moves.length)];
          previous = face;
          const move = Math.random() > 0.5 ? face : `${face}'`;
          moveCube(state.cube, move);
          state.solutionStack.push(inverseMove(move));
        }
        hintEl.textContent = "已打亂。可自行解題，或按提示看下一個建議反向步。";
        render();
      };
      const resetSolved = () => {
        state.cube = createSolvedCube();
        state.solutionStack = [];
        state.moves = 0;
        state.score = 0;
        state.active = false;
        state.solved = true;
        state.startedAt = 0;
        hintEl.textContent = "已重置為完成狀態。";
        render();
      };
      const autoSolve = () => {
        if (!state.solutionStack.length) {
          hintEl.textContent = "沒有可用解題步驟。";
          return;
        }
        const stack = state.solutionStack.splice(0);
        stack.reverse().forEach((move) => moveCube(state.cube, move));
        state.moves += stack.length;
        state.active = false;
        state.solved = true;
        state.score = Math.max(50, scoreFor(state) - 500);
        hintEl.textContent = `自動還原完成，使用 ${stack.length} 步。`;
        render();
      };
      const showHint = () => {
        const move = state.solutionStack[state.solutionStack.length - 1] || "";
        hintEl.textContent = move ? `提示：下一步可試 ${move}。` : "目前沒有提示，可能已經接近完成。";
      };
      const rotateView = (dir) => {
        if (dir === "left") state.viewY -= 18;
        if (dir === "right") state.viewY += 18;
        if (dir === "up") state.viewX -= 14;
        if (dir === "down") state.viewX += 14;
        state.viewX = Math.max(-75, Math.min(55, state.viewX));
        render();
      };

      stage.addEventListener("pointerdown", (event) => {
        state.drag = { x: event.clientX, y: event.clientY, viewX: state.viewX, viewY: state.viewY };
        stage.setPointerCapture?.(event.pointerId);
      });
      stage.addEventListener("pointermove", (event) => {
        if (!state.drag) return;
        state.viewY = state.drag.viewY + (event.clientX - state.drag.x) * 0.35;
        state.viewX = Math.max(-75, Math.min(55, state.drag.viewX - (event.clientY - state.drag.y) * 0.28));
        render();
      });
      stage.addEventListener("pointerup", () => { state.drag = null; });
      stage.addEventListener("pointercancel", () => { state.drag = null; });

      api.onAction = (action) => {
        if (action === "new") scramble();
        if (action === "reset") resetSolved();
        if (action === "solve") autoSolve();
        if (action === "hint") showHint();
      };
      api.onControl = (target) => {
        const move = target?.dataset?.rubiksMove || "";
        const view = target?.dataset?.rubiksView || "";
        if (move) applyMove(move);
        if (view) rotateView(view);
      };
      api.onKey = (event, pressed) => {
        if (!pressed) return;
        const key = String(event.key || "").toUpperCase();
        if (FACE_AXES[key]) {
          event.preventDefault?.();
          applyMove(event.shiftKey ? `${key}'` : key);
          return;
        }
        const viewKey = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" }[event.key];
        if (viewKey) {
          event.preventDefault?.();
          rotateView(viewKey);
        }
      };
      render();
    },
  });
}());
