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
    api.root.innerHTML = `
      <div class="board-game-clock" data-board-clock>
        <span data-board-clock-side="black">黑 --:--</span>
        <span data-board-clock-side="white">白 --:--</span>
      </div>
      <div class="board-game-coach" data-board-coach></div>
      <div class="board-game-grid ${type}" style="--board-size:${size}" aria-label="${title}"></div>
    `;
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
      hintCells: new Set(),
      coachText: "",
      renjuForbidden: false,
      captures: { black: 0, white: 0 },
      dailyChallenge: api.dailyChallenge?.() || null,
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
    const clock = window.createHackmeCompetitionClock?.({
      onExpire(side) {
        if (state.finished) return;
        const winner = other(side);
        finish(winner === "black" ? "黑方超時" : "白方超時");
        render();
      },
    }) || null;
    const clockPresetLabel = () => {
      const preset = window.gameClockPreset?.(clock?.state.presetKey || "rapid_10_0");
      return preset?.label || "Rapid 10+0";
    };
    const applyClockPreset = (presetKey) => {
      if (!clock) return;
      const preset = window.gameClockPreset?.(presetKey) || window.gameClockPreset?.("rapid_10_0");
      if (!preset) return;
      clock.configure({
        presetKey: preset.key,
        mainSeconds: preset.mainSeconds,
        incrementSeconds: preset.incrementSeconds,
      });
      clock.reset(state.turn);
    };
    const renderClock = (snapshot = clock?.state) => {
      if (!snapshot) return;
      const clockEl = api.root.querySelector("[data-board-clock]");
      if (!clockEl) return;
      clockEl.classList.toggle("enabled", Boolean(snapshot.enabled));
      clockEl.classList.toggle("expired", Boolean(snapshot.expiredSide));
      ["black", "white"].forEach((side) => {
        const el = clockEl.querySelector(`[data-board-clock-side="${side}"]`);
        if (!el) return;
        const value = side === "black" ? snapshot.blackMs : snapshot.whiteMs;
        el.textContent = `${side === "black" ? "黑" : "白"} ${window.formatHackmeGameClock?.(value) || "--:--"}`;
        el.classList.toggle("active", snapshot.enabled && snapshot.running && snapshot.activeSide === side && !snapshot.expiredSide);
        el.classList.toggle("expired", snapshot.expiredSide === side);
      });
    };
    const unsubscribeClock = clock?.subscribe(renderClock) || null;
    const setActions = () => {
      const nextModeLabel = state.mode === "computer" ? "玩家對戰" : "對電腦";
      const sideButton = state.mode === "computer"
        ? `<button class="btn game-mini-btn" type="button" data-action="side">${playerOrderLabel()}</button>`
        : "";
      const clockButtons = clock ? `
        <button class="btn game-mini-btn" type="button" data-action="clock">${clock.state.enabled ? "計時開" : "計時關"}</button>
        <button class="btn game-mini-btn" type="button" data-action="clock-preset">${clockPresetLabel()}</button>
      ` : "";
      const forbiddenButton = type === "gomoku"
        ? `<button class="btn game-mini-btn" type="button" data-action="forbidden">禁手${state.renjuForbidden ? "開" : "關"}</button>`
        : "";
      api.setActions(`
        <button class="btn game-mini-btn btn-primary" type="button" data-action="new">新局</button>
        <button class="btn game-mini-btn" type="button" data-action="mode">${nextModeLabel}</button>
        ${sideButton}
        <button class="btn game-mini-btn" type="button" data-action="difficulty">AI ${difficultyLabel()}</button>
        <button class="btn game-mini-btn" type="button" data-action="hint">提示</button>
        ${forbiddenButton}
        ${clockButtons}
        <button class="btn game-mini-btn" type="button" data-action="pass">停一手</button>
        <button class="btn game-mini-btn" type="button" data-action="finish">結算</button>
      `);
    };
    const status = (text) => api.status(text);
    const boardCoach = () => api.root.querySelector("[data-board-coach]");
    const setCoach = (text) => {
      state.coachText = text || "";
      const coach = boardCoach();
      if (coach) coach.textContent = state.coachText;
    };
    const aiStrengthText = () => {
      const text = window.HACKME_GAME_AI_STRENGTH?.[type]?.[state.aiDifficulty] || "";
      return text ? `AI 棋力：${text}` : "";
    };
    const legalMovesFor = (color) => {
      if (isReversi) {
        return state.board.map((_value, i) => {
          const [x, y] = xy(i);
          return !state.board[i] && reversiFlips(x, y, color).length ? i : null;
        }).filter((value) => value !== null);
      }
      if (type === "go") {
        return state.board.map((_value, i) => {
          if (state.board[i]) return null;
          const copy = state.board.slice();
          const [x, y] = xy(i);
          copy[i] = color;
          let captured = 0;
          const opponent = other(color);
          for (const [nx, ny] of neighbors(x, y)) {
            const ni = idx(nx, ny);
            if (copy[ni] !== opponent) continue;
            const group = libertiesFromBoard(copy, ni, opponent);
            if (!group.libs.size) captured += group.group.size;
          }
          const own = libertiesFromBoard(copy, i, color);
          return own.libs.size || captured ? i : null;
        }).filter((value) => value !== null);
      }
      return state.board.map((value, i) => value ? null : i).filter((value) => value !== null);
    };
    const renderCoach = () => {
      const coach = boardCoach();
      if (!coach) return;
      const strength = state.mode === "computer" ? aiStrengthText() : "";
      coach.textContent = [state.coachText, strength].filter(Boolean).join(" · ");
    };
    const finish = (winner = "") => {
      state.finished = true;
      state.aiThinking = false;
      aiToken += 1;
      clock?.stop();
      const black = count("black");
      const white = count("white");
      const score = Math.max(1, black * 10 + (black > white ? 200 : 0));
      if (winner && state.mode === "computer" && winner.includes(state.humanColor === "black" ? "黑" : "白")) {
        api.achievement?.("beat-ai", `${title}勝 AI`, `以 ${difficultyLabel()} 難度獲勝。`);
        api.mission?.("win-ai", 1, 1, "擊敗 AI");
      }
      registerScore(api, score, state, state.dailyChallenge?.difficulty || "standard");
      status(`${winner ? `${winner}勝 · ` : ""}結束 · 黑 ${black} / 白 ${white}`);
    };
    const renderStatus = () => {
      if (state.finished) return;
      const side = state.turn === "black" ? "黑" : "白";
      const mode = state.mode === "computer" ? `對電腦 ${difficultyLabel()} · ${playerOrderLabel()}` : "玩家對戰";
      const actor = state.mode === "computer" ? (isAiTurn() ? "AI" : "玩家") : "玩家";
      status(`${state.aiThinking ? "AI 思考中" : `${side}方走`} · ${actor} · 黑 ${count("black")} / 白 ${count("white")} · ${mode}`);
      renderClock();
    };
    const render = () => {
      const locked = inputLocked();
      const cells = state.board.map((value, i) => (
        `<button class="board-game-cell ${value} ${state.hintCells.has(i) ? "hint" : ""}" type="button" data-i="${i}" aria-label="${i}" ${locked ? "disabled" : ""}>${value ? `<span></span>` : ""}</button>`
      )).join("");
      const overlay = state.finished
        ? `<div class="single-game-over-overlay">GAME OVER<br><small>${title} · 黑 ${count("black")} / 白 ${count("white")}</small></div>`
        : "";
      boardEl.innerHTML = cells + overlay;
      renderStatus();
      renderCoach();
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
      return libertiesFromBoard(state.board, start, color);
    };
    const libertiesFromBoard = (board, start, color) => {
      const stack = [start], group = new Set(), libs = new Set();
      while (stack.length) {
        const current = stack.pop(); if (group.has(current)) continue; group.add(current);
        const [x, y] = xy(current);
        for (const [nx, ny] of neighbors(x, y)) {
          const ni = idx(nx, ny), value = board[ni];
          if (!value) libs.add(ni); else if (value === color && !group.has(ni)) stack.push(ni);
        }
      }
      return { group, libs };
    };
    const gomokuLineInfo = (x, y, color, dx, dy, board = state.board) => {
      let total = 1;
      let openEnds = 0;
      for (const sign of [1, -1]) {
        let nx = x + dx * sign, ny = y + dy * sign;
        while (inBounds(nx, ny) && board[idx(nx, ny)] === color) { total += 1; nx += dx * sign; ny += dy * sign; }
        if (inBounds(nx, ny) && !board[idx(nx, ny)]) openEnds += 1;
      }
      return { total, openEnds };
    };
    const gomokuWin = (x, y, color) => [[1, 0], [0, 1], [1, 1], [1, -1]].some(([dx, dy]) => {
      const line = gomokuLineInfo(x, y, color, dx, dy);
      return line.total >= 5;
    });
    const isGomokuForbiddenMove = (i, color) => {
      if (type !== "gomoku" || color !== "black") return false;
      const board = state.board.slice();
      board[i] = color;
      const [x, y] = xy(i);
      let openThrees = 0;
      let openFours = 0;
      for (const [dx, dy] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
        const line = gomokuLineInfo(x, y, color, dx, dy, board);
        if (line.total > 5) return true;
        if (line.total === 3 && line.openEnds >= 2) openThrees += 1;
        if (line.total === 4 && line.openEnds >= 2) openFours += 1;
      }
      return openThrees >= 2 || openFours >= 2;
    };
    const estimateGoTerritory = () => {
      let black = count("black") + state.captures.black;
      let white = count("white") + state.captures.white;
      state.board.forEach((value, i) => {
        if (value) return;
        const adj = [...neighbors(...xy(i))].map(([nx, ny]) => state.board[idx(nx, ny)]);
        if (adj.includes("black") && !adj.includes("white")) black += 0.5;
        if (adj.includes("white") && !adj.includes("black")) white += 0.5;
      });
      return { black, white };
    };
    const lineThreatMove = (color) => {
      const moves = legalMovesFor(color);
      for (const move of moves) {
        const [x, y] = xy(move);
        const board = state.board.slice();
        board[move] = color;
        if ([[1, 0], [0, 1], [1, 1], [1, -1]].some(([dx, dy]) => gomokuLineInfo(x, y, color, dx, dy, board).total >= 5)) return { move, reason: "直接五連勝手" };
      }
      for (const move of moves) {
        const [x, y] = xy(move);
        const board = state.board.slice();
        board[move] = color;
        if ([[1, 0], [0, 1], [1, 1], [1, -1]].some(([dx, dy]) => {
          const line = gomokuLineInfo(x, y, color, dx, dy, board);
          return line.total >= 4 && line.openEnds >= 1;
        })) return { move, reason: "形成四連威脅" };
      }
      return { move: moves[0], reason: "靠近既有棋形發展" };
    };
    const showHint = () => {
      state.hintCells = new Set();
      if (state.finished) return;
      const color = state.turn;
      if (isReversi) {
        const moves = legalMovesFor(color);
        const corners = moves.filter((i) => [0, 7, 56, 63].includes(i));
        const safe = corners[0] ?? moves.sort((a, b) => reversiFlips(...xy(b), color).length - reversiFlips(...xy(a), color).length)[0];
        if (safe !== undefined) {
          state.hintCells.add(safe);
          const cornerText = corners.length ? "角落是最高優先，能永久穩定。" : "避免太早下角旁 C/X 格，先提高行動力。";
          setCoach(`提示：${cornerText}`);
        }
      } else if (type === "go") {
        const moves = legalMovesFor(color);
        const captureMove = moves.find((move) => {
          const [x, y] = xy(move);
          return neighbors(x, y).some(([nx, ny]) => {
            const ni = idx(nx, ny);
            return state.board[ni] === other(color) && liberties(ni, other(color)).libs.size === 1;
          });
        });
        const pick = captureMove ?? moves.sort((a, b) => Math.abs(xy(a)[0] - 4) + Math.abs(xy(a)[1] - 4) - (Math.abs(xy(b)[0] - 4) + Math.abs(xy(b)[1] - 4)))[0];
        if (pick !== undefined) state.hintCells.add(pick);
        const territory = estimateGoTerritory();
        if (territory.black > territory.white && color === "black") api.mission?.("territory", 1, 1, "地盤估算領先");
        setCoach(`地盤估算：黑 ${territory.black.toFixed(1)} / 白 ${territory.white.toFixed(1)}。提示優先救叫吃或吃子。`);
      } else {
        const own = lineThreatMove(color);
        const block = lineThreatMove(other(color));
        const pick = own.reason.includes("勝") || own.reason.includes("四") ? own : block;
        if (pick.move !== undefined) state.hintCells.add(pick.move);
        setCoach(`威脅提示：${pick.reason}${state.renjuForbidden ? "；黑方已啟用禁手檢查。" : ""}`);
      }
      render();
    };
    const applyMove = (i) => {
      if (state.finished || state.board[i]) return false;
      const [x, y] = xy(i);
      if (isReversi) {
        const flips = reversiFlips(x, y, state.turn);
        if (!flips.length) return false;
        state.board[i] = state.turn;
        flips.forEach((fi) => { state.board[fi] = state.turn; });
        if ([0, 7, 56, 63].includes(i)) {
          api.achievement?.("corner", "角落意識", "佔領至少一個角落。");
          api.mission?.("corner", 1, 1, "佔領角落");
        }
      } else {
        if (type === "gomoku" && state.renjuForbidden && isGomokuForbiddenMove(i, state.turn)) {
          setCoach("禁手：黑方不可長連、雙活三或雙活四。");
          api.achievement?.("renju-clean", "禁手自律", "連珠規則下避免禁手。");
          return false;
        }
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
          if (captured) {
            state.captures[state.turn] += captured;
            api.achievement?.("capture", "吃子入門", "圍棋吃掉對方棋子。");
            api.mission?.("capture", captured, 1, "圍棋吃子");
          }
        }
        if (type === "gomoku" && gomokuWin(x, y, state.turn)) {
          const winner = state.turn === "black" ? "黑" : "白";
          api.achievement?.("threat", "威脅建構", "形成五連勝手。");
          api.mission?.("win", 1, 1, "五子連線勝");
          finish(winner);
          render();
          return true;
        } else if (type === "gomoku") {
          const openFour = [[1, 0], [0, 1], [1, 1], [1, -1]].some(([dx, dy]) => {
            const line = gomokuLineInfo(x, y, state.turn, dx, dy);
            return line.total >= 4 && line.openEnds >= 2;
          });
          if (openFour) {
            api.achievement?.("threat", "威脅建構", "形成活四。");
            api.mission?.("open-four", 1, 1, "形成活四");
          }
        }
      }
      state.passCount = 0;
      state.hintCells = new Set();
      state.turn = other(state.turn);
      clock?.switchTurn(state.turn);
      render();
      queueAiMove();
      return true;
    };
    const passTurn = () => {
      if (state.finished) return;
      state.passCount += 1;
      state.turn = other(state.turn);
      clock?.switchTurn(state.turn);
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
      state.hintCells = new Set();
      state.captures = { black: 0, white: 0 };
      state.dailyChallenge = api.dailyChallenge?.() || null;
      setCoach(state.dailyChallenge?.label || "");
      if (isReversi) {
        state.board[idx(3, 3)] = "white"; state.board[idx(4, 4)] = "white";
        state.board[idx(3, 4)] = "black"; state.board[idx(4, 3)] = "black";
      }
      clock?.reset(state.turn);
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
        setCoach(aiStrengthText());
        render();
      }
      if (action === "hint") showHint();
      if (action === "forbidden" && type === "gomoku") {
        state.renjuForbidden = !state.renjuForbidden;
        setCoach(state.renjuForbidden ? "連珠禁手已啟用：黑方長連、雙活三、雙活四不可下。" : "連珠禁手已關閉。");
        render();
      }
      if (action === "clock" && clock) {
        clock.configure({ enabled: !clock.state.enabled });
        clock.reset(state.turn);
        render();
        queueAiMove();
      }
      if (action === "clock-preset" && clock) {
        const presets = window.HACKME_GAME_CLOCK_PRESETS || [];
        const index = presets.findIndex((preset) => preset.key === clock.state.presetKey);
        const nextPreset = presets[(index + 1) % presets.length] || presets[0];
        applyClockPreset(nextPreset?.key || "rapid_10_0");
        render();
      }
    };
    api.root.onclick = (event) => {
      const btn = event.target.closest("[data-i]");
      if (!btn || inputLocked()) return;
      applyMove(Number(btn.dataset.i));
    };
    reset();
    return () => { aiToken += 1; clock?.stop(); unsubscribeClock?.(); };
  }

  window.mountHackmeLocalDiscGame = mountLocalDiscGame;
}());
