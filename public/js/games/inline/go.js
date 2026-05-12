'use strict';

(function () {
  window.registerHackmeInlineGameModule("go", {
    mount(api) {
      return window.mountHackmeInlineDiscGame(api, "go");
    },
  });
}());
