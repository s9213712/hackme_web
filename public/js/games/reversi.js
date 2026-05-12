'use strict';

(function () {
  window.registerHackmeLocalGameModule("reversi", {
    mount(api) {
      return window.mountHackmeLocalDiscGame(api, "reversi");
    },
  });
}());
