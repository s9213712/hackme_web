'use strict';

let oneA2BState = null;
let oneA2BTimedMode = false;

function setOneA2BNotice(text, ms = 3500) {
  if (!oneA2BState) return;
  oneA2BState.notice = text || "";
  oneA2BState.noticeUntil = text ? Date.now() + ms : 0;
}

function generateOneA2BSecret() {
  const digits = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];
  const secret = [];
  while (secret.length < 4) {
    const index = Math.floor(Math.random() * digits.length);
    const digit = digits[index];
    if (!secret.length && digit === "0") continue;
    secret.push(digits.splice(index, 1)[0]);
  }
  return secret.join("");
}

function scoreOneA2BGuess(secret, guess) {
  let a = 0;
  let b = 0;
  for (let i = 0; i < 4; i += 1) {
    if (guess[i] === secret[i]) a += 1;
    else if (secret.includes(guess[i])) b += 1;
  }
  return { a, b };
}

function normalizeOneA2BGuess(value) {
  return String(value || "").replace(/\D/g, "").slice(0, 4);
}

function isValidOneA2BGuess(value) {
  return /^[1-9][0-9]{3}$/.test(value) && new Set(value.split("")).size === 4;
}

function startOneA2BGame() {
  const dailyChallenge = window.hackmeGameDailyChallenge?.("1a2b") || null;
  oneA2BState = {
    secret: generateOneA2BSecret(),
    startedAt: Date.now(),
    completedAt: null,
    penaltySeconds: 0,
    scoreSubmitted: false,
    difficulty: dailyChallenge?.difficulty || "standard",
    puzzleId: dailyChallenge?.key || "1a2b-4digits",
    guesses: [],
    timedMode: oneA2BTimedMode,
    aiDeadlineMs: 90000 + Math.floor(Math.random() * 45000),
    hintsUsed: 0,
    dailyChallenge,
  };
  const input = $("onea2b-guess-input");
  if (input) {
    input.value = "";
    input.disabled = false;
    input.focus();
  }
  renderOneA2BBoard();
  ensureSoloGameTimer();
  updateOneA2BModeButton();
  updateOneA2BStatus(`${dailyChallenge?.label || "計時開始"}。輸入 4 個不重複數字，首位不可為 0，例如 1234。`);
}

function renderOneA2BBoard() {
  const board = $("onea2b-history");
  if (!board) return;
  if (!oneA2BState) {
    board.innerHTML = '<div class="single-game-placeholder">按「開始」後才會產生題目並開始計時。</div>';
    return;
  }
  if (!oneA2BState.guesses.length) {
    board.innerHTML = '<div class="single-game-placeholder">尚未猜測。A 是位置正確，B 是數字正確但位置不同。</div>';
    return;
  }
  board.innerHTML = oneA2BState.guesses.map((item, index) => `
    <div class="onea2b-row ${item.a === 4 ? "solved" : ""}">
      <strong>#${index + 1} ${sanitize(item.guess)}</strong>
      <span>${Number(item.a)}A${Number(item.b)}B</span>
    </div>
  `).join("");
}

function updateOneA2BStatus(prefix = "") {
  const status = $("onea2b-status");
  if (!status) return;
  if (!oneA2BState) {
    status.textContent = "按開始後才會產生答案並開始計時。";
    return;
  }
  const time = formatSoloGameTime(soloElapsedMs(oneA2BState));
  if (oneA2BState.completedAt) {
    const race = oneA2BState.timedMode ? (soloElapsedMs(oneA2BState) <= oneA2BState.aiDeadlineMs ? " · 贏過 AI 對手" : " · AI 對手先解出") : "";
    status.textContent = `完成時間 ${time} · 共 ${oneA2BState.guesses.length} 次${race}`;
    return;
  }
  const activeNotice = oneA2BState.notice && Date.now() < Number(oneA2BState.noticeUntil || 0)
    ? oneA2BState.notice
    : "";
  if (!activeNotice) {
    oneA2BState.notice = "";
    oneA2BState.noticeUntil = 0;
  }
  const head = activeNotice || prefix || "";
  const race = oneA2BState.timedMode ? ` · AI 對手 ${formatSoloGameTime(oneA2BState.aiDeadlineMs)}` : "";
  status.textContent = `${head ? `${head} ` : ""}目前時間 ${time} · 已猜 ${oneA2BState.guesses.length} 次 · 提示 ${oneA2BState.hintsUsed}${race}`;
}

function updateOneA2BModeButton() {
  const btn = $("onea2b-mode-btn");
  if (!btn) return;
  btn.classList.toggle("btn-primary", oneA2BTimedMode);
  btn.textContent = oneA2BTimedMode ? "限時開" : "限時關";
}

function submitOneA2BGuess() {
  if (!oneA2BState || oneA2BState.completedAt) return;
  const input = $("onea2b-guess-input");
  const guess = normalizeOneA2BGuess(input?.value || "");
  if (input && input.value !== guess) input.value = guess;
  if (!isValidOneA2BGuess(guess)) {
    setOneA2BNotice("請輸入 4 個不重複數字，首位不可為 0。");
    updateOneA2BStatus();
    return;
  }
  if (oneA2BState.guesses.some((item) => item.guess === guess)) {
    setOneA2BNotice("這組數字已猜過。");
    updateOneA2BStatus();
    return;
  }
  const result = scoreOneA2BGuess(oneA2BState.secret, guess);
  oneA2BState.guesses.push({ guess, ...result });
  if (input) {
    input.value = "";
    input.focus();
  }
  renderOneA2BBoard();
  if (result.a === 4) {
    oneA2BState.completedAt = Date.now();
    if (input) input.disabled = true;
    updateOneA2BStatus();
    stopSoloGameTimerIfIdle();
    if (soloElapsedMs(oneA2BState) <= 120000) window.recordHackmeGameAchievement?.("1a2b", "quick-crack", "快速破譯", "2 分鐘內完成。");
    if (oneA2BState.guesses.length <= 6) window.recordHackmeGameAchievement?.("1a2b", "few-guesses", "精準猜測", "6 次內完成。");
    if (oneA2BState.hintsUsed) window.recordHackmeGameAchievement?.("1a2b", "hint-win", "提示取捨", "使用提示後仍完成。");
    if (soloElapsedMs(oneA2BState) > 5 * 60 * 1000) {
      oneA2BState.scoreSubmitted = true;
      setGameMsg("1A2B 已完成，但超過 5 分鐘，不列入排行榜。", false);
      return;
    }
    submitSoloGameScore("1a2b", oneA2BState);
    setGameMsg(`1A2B 完成，成績 ${formatSoloGameTime(soloElapsedMs(oneA2BState))}`, true);
    return;
  }
  updateOneA2BStatus(`${result.a}A${result.b}B`);
}

function toggleOneA2BTimedMode() {
  oneA2BTimedMode = !oneA2BTimedMode;
  updateOneA2BModeButton();
  updateOneA2BStatus(oneA2BTimedMode ? "限時競速開啟。" : "限時競速關閉。");
}

function useOneA2BHint() {
  if (!oneA2BState || oneA2BState.completedAt) return;
  const unrevealed = [0, 1, 2, 3].filter((index) => !oneA2BState.guesses.some((item) => item.guess[index] === oneA2BState.secret[index]));
  const index = unrevealed[0] ?? Math.min(3, oneA2BState.hintsUsed);
  oneA2BState.hintsUsed += 1;
  oneA2BState.penaltySeconds += 15;
  setOneA2BNotice(`提示：第 ${index + 1} 位是 ${oneA2BState.secret[index]}，代價加時 15 秒。`, 5000);
  updateOneA2BStatus();
}

function handleOneA2BKeypad(key) {
  if (!oneA2BState) startOneA2BGame();
  if (!oneA2BState || oneA2BState.completedAt) return;
  const input = $("onea2b-guess-input");
  if (!input) return;
  const current = normalizeOneA2BGuess(input.value || "");
  if (key === "enter") {
    submitOneA2BGuess();
    return;
  }
  if (key === "back") {
    input.value = current.slice(0, -1);
    input.focus();
    return;
  }
  if (key === "clear") {
    input.value = "";
    input.focus();
    return;
  }
  if (!/^\d$/.test(String(key || ""))) return;
  if (!current && key === "0") {
    setOneA2BNotice("首位不可為 0。");
    updateOneA2BStatus();
    input.focus();
    return;
  }
  if (current.includes(key)) {
    setOneA2BNotice("同一組猜測不能重複使用數字。");
    updateOneA2BStatus();
    input.focus();
    return;
  }
  input.value = normalizeOneA2BGuess(`${current}${key}`);
  input.focus();
  if (input.value.length >= 4) updateOneA2BStatus("已輸入 4 位，可送出。");
}

(function () {
  window.registerHackmeGameViewModule?.({
    key: "1a2b",
    panelIds: ["onea2b-game-panel"],
    ensure() {
      if (!oneA2BState) {
        renderOneA2BBoard();
        updateOneA2BStatus();
      }
    },
    updateStatus() {
      updateOneA2BStatus();
    },
    isActive() {
      return !!oneA2BState && !oneA2BState.completedAt;
    },
    leaderboardPath() {
      return "/games/1a2b/solo-leaderboard";
    },
    dispatch(type, event) {
      if (type === "click" && event.target?.closest?.("#onea2b-new-btn")) {
        startOneA2BGame();
        return true;
      }
      if (type === "click" && event.target?.closest?.("#onea2b-mode-btn")) {
        toggleOneA2BTimedMode();
        return true;
      }
      if (type === "click" && event.target?.closest?.("#onea2b-hint-btn")) {
        useOneA2BHint();
        return true;
      }
      if (type === "click" && event.target?.closest?.("#onea2b-guess-btn")) {
        submitOneA2BGuess();
        return true;
      }
      const keypadBtn = type === "click" ? event.target?.closest?.("[data-onea2b-key]") : null;
      if (keypadBtn) {
        handleOneA2BKeypad(keypadBtn.dataset.onea2bKey || "");
        return true;
      }
      const guessInput = event.target?.closest?.("#onea2b-guess-input");
      if (type === "input" && guessInput) {
        guessInput.value = normalizeOneA2BGuess(guessInput.value || "");
        return true;
      }
      if (type === "keydown" && guessInput && event.key === "Enter") {
        event.preventDefault();
        submitOneA2BGuess();
        return true;
      }
      return false;
    },
  });
}());
