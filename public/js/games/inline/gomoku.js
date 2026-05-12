'use strict';

(function () {
  window.registerHackmeInlineGameModule("gomoku", {
    mount(api) {
      return window.mountHackmeInlineDiscGame(api, "gomoku");
    },
  });
}());
