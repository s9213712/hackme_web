'use strict';

(function () {
  const modules = window.HACKME_GAME_VIEW_MODULES || {};

  window.HACKME_GAME_VIEW_MODULES = modules;
  window.registerHackmeGameViewModule = function registerHackmeGameViewModule(module) {
    if (!module || !module.key) return;
    modules[module.key] = module;
  };
}());
