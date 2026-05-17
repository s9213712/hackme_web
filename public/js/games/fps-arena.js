'use strict';

(function () {
  const HOLD_TOUCH_ACTIONS = new Set(["fps-left", "fps-right", "fps-forward", "fps-back", "fps-fire", "fps-sprint"]);
  const activeTouchActions = new Map();
  let suppressTouchClickUntil = 0;

  function setFpsTouchHold(action, pressed) {
    if (typeof window.handleFpsArenaTouchHold === "function") {
      window.handleFpsArenaTouchHold(action, pressed);
    }
  }

  function releaseFpsTouchPointer(pointerId) {
    const action = activeTouchActions.get(pointerId);
    if (!action) return;
    activeTouchActions.delete(pointerId);
    setFpsTouchHold(action, false);
  }

  function bindFpsArenaTouchButtonHold() {
    if (bindFpsArenaTouchButtonHold.bound) return;
    bindFpsArenaTouchButtonHold.bound = true;
    document.addEventListener("pointerdown", (event) => {
      const button = event.target?.closest?.("#fps-arena-game-panel [data-game-touch]");
      const action = button?.dataset.gameTouch || "";
      if (!HOLD_TOUCH_ACTIONS.has(action)) return;
      event.preventDefault();
      suppressTouchClickUntil = Date.now() + 450;
      activeTouchActions.set(event.pointerId, action);
      button.classList.add("is-held");
      try {
        button.setPointerCapture?.(event.pointerId);
      } catch (_) {}
      setFpsTouchHold(action, true);
    }, { passive: false });
    ["pointerup", "pointercancel", "lostpointercapture"].forEach((type) => {
      document.addEventListener(type, (event) => {
        const button = event.target?.closest?.("#fps-arena-game-panel [data-game-touch]");
        if (button) button.classList.remove("is-held");
        releaseFpsTouchPointer(event.pointerId);
      });
    });
  }

  window.registerHackmeGameViewModule?.({
    key: "fps_arena",
    panelIds: ["fps-arena-game-panel"],
    ensure() {
      bindFpsArenaTouchButtonHold();
      if (typeof window.renderFpsArenaBoard === "function") {
        window.renderFpsArenaBoard();
      }
      if (typeof window.updateFpsArenaStatus === "function") {
        window.updateFpsArenaStatus();
      }
    },
    updateStatus() {
      if (typeof window.updateFpsArenaStatus === "function") {
        window.updateFpsArenaStatus();
      }
    },
    isActive() {
      return typeof window.isFpsArenaActive === "function" && window.isFpsArenaActive();
    },
    suspend() {
      if (typeof window.suspendFpsArenaGame === "function") window.suspendFpsArenaGame();
    },
    leaderboardPath() {
      const mode = typeof window.currentFpsArenaDifficulty === "function"
        ? window.currentFpsArenaDifficulty()
        : (typeof window.currentFpsArenaMode === "function" ? window.currentFpsArenaMode() : "aim");
      return `/games/fps_arena/solo-leaderboard?difficulty=${encodeURIComponent(mode)}`;
    },
    dispatch(type, event, runtime) {
      if (type === "click" && event.target?.closest?.("#fps-arena-new-btn")) {
        if (typeof window.startFpsArenaGame === "function") window.startFpsArenaGame();
        return true;
      }
      if (type === "click" && event.target?.closest?.("#fps-arena-stop-btn")) {
        if (typeof window.finishFpsArenaGame === "function") window.finishFpsArenaGame("manual");
        return true;
      }
      const touchBtn = type === "click" ? event.target?.closest?.("[data-game-touch]") : null;
      if (touchBtn && String(touchBtn.dataset.gameTouch || "").startsWith("fps-")) {
        if (Date.now() < suppressTouchClickUntil && HOLD_TOUCH_ACTIONS.has(touchBtn.dataset.gameTouch || "")) return true;
        if (typeof window.handleFpsArenaTouch === "function") window.handleFpsArenaTouch(touchBtn.dataset.gameTouch || "");
        return true;
      }
      if (type === "change" && event.target?.closest?.("#fps-arena-mode, #fps-arena-level")) {
        if (typeof window.renderFpsArenaBoard === "function") window.renderFpsArenaBoard();
        if (typeof window.updateFpsArenaStatus === "function") window.updateFpsArenaStatus();
        runtime.loadSelectedGameLeaderboard().catch((err) => runtime.setGameMsg(err.message || "排行榜讀取失敗", false));
        return true;
      }
      if (type === "keydown" && typeof window.handleFpsArenaKey === "function") {
        window.handleFpsArenaKey(event, true);
        return true;
      }
      if (type === "keyup" && typeof window.handleFpsArenaKey === "function") {
        window.handleFpsArenaKey(event, false);
        return true;
      }
      return false;
    },
  });
}());
