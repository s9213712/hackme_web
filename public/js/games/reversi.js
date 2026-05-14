'use strict';

(function () {
  if (typeof window.mountHackmeLocalDiscGame !== "function") return;
  window.registerHackmeLocalGameModule("reversi", {
    mount(api) {
      return window.mountHackmeLocalDiscGame(api, "reversi");
    },
  });
}());
