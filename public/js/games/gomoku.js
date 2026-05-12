'use strict';

(function () {
  window.registerHackmeLocalGameModule("gomoku", {
    mount(api) {
      return window.mountHackmeLocalDiscGame(api, "gomoku");
    },
  });
}());
