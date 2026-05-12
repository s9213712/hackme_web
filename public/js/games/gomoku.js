'use strict';

(function () {
  if (typeof window.mountHackmeLocalDiscGame !== "function") return;
  window.registerHackmeLocalGameModule("gomoku", {
    mount(api) {
      return window.mountHackmeLocalDiscGame(api, "gomoku");
    },
  });
}());
