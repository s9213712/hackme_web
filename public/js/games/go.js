'use strict';

(function () {
  window.registerHackmeLocalGameModule("go", {
    mount(api) {
      return window.mountHackmeLocalDiscGame(api, "go");
    },
  });
}());
