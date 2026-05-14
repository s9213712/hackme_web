'use strict';

(function () {
  if (typeof window.mountHackmeLocalDiscGame !== "function") return;
  window.registerHackmeLocalGameModule("go", {
    mount(api) {
      return window.mountHackmeLocalDiscGame(api, "go");
    },
  });
}());
