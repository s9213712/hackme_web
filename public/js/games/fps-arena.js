'use strict';

(function () {
  window.registerHackmeGameViewModule?.({
    key: "fps_arena",
    panelIds: ["fps-arena-game-panel"],
    ensure() {
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
    leaderboardPath() {
      const mode = typeof window.currentFpsArenaMode === "function" ? window.currentFpsArenaMode() : "aim";
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
        if (typeof window.handleFpsArenaTouch === "function") window.handleFpsArenaTouch(touchBtn.dataset.gameTouch || "");
        return true;
      }
      if (type === "change" && event.target?.closest?.("#fps-arena-mode")) {
        if (typeof window.renderFpsArenaBoard === "function") window.renderFpsArenaBoard();
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
