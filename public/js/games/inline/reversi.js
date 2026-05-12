'use strict';

(function () {
  window.registerHackmeInlineGameModule("reversi", {
    mount(api) {
      return window.mountHackmeInlineDiscGame(api, "reversi");
    },
  });
}());
