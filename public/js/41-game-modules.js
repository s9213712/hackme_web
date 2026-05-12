'use strict';

(function () {
  const catalog = [
    { key: "chess", title: "西洋棋", subtitle: "玩家對戰 / 電腦練習", legacy: true },
    { key: "sudoku", title: "數獨", subtitle: "單人邏輯解題", legacy: true },
    { key: "minesweeper", title: "踩地雷", subtitle: "單人推理挑戰", legacy: true },
    { key: "1a2b", title: "1A2B", subtitle: "單人猜數字", legacy: true },
    { key: "tetris", title: "俄羅斯方塊", subtitle: "高分消除挑戰", legacy: true },
    { key: "space_shooter", title: "宇宙戰機", subtitle: "高分射擊挑戰", legacy: true },
    { key: "fps_arena", title: "3D 射擊場", subtitle: "四模式 3D 射擊訓練", legacy: true },
    { key: "snake", title: "貪食蛇", subtitle: "滑動或方向鍵控制蛇吃食物" },
    { key: "game_2048", title: "2048", subtitle: "合併數字方塊，挑戰最高分" },
    { key: "brick_breaker", title: "打磚塊", subtitle: "移動擋板反彈球打掉磚塊" },
    { key: "reversi", title: "黑白棋", subtitle: "AI 練習 / 本機雙人" },
    { key: "go", title: "圍棋", subtitle: "9 路簡化圍棋，AI 練習 / 本機雙人" },
    { key: "gomoku", title: "五子棋", subtitle: "15 路 AI 練習 / 本機雙人" },
  ];

  const modules = window.HACKME_GAME_MODULES || {};
  const byKey = (key) => catalog.find((game) => game.key === key) || catalog[0];
  const cell = (value, cls = "") => `<button class="${cls}" type="button">${value || ""}</button>`;
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  function makeCtx(api, title) {
    api.setTitle(title);
    api.setActions(`<button class="btn game-mini-btn btn-primary" type="button" data-action="new">開始</button>`);
  }

  function registerScore(api, score, state, difficulty = "standard") {
    if (!score || score <= 0) return;
    api.submitScore({
      score,
      difficulty,
      puzzle_id: api.key,
      raw_elapsed_ms: Math.max(1, Date.now() - state.startedAt),
      elapsed_ms: Math.max(1, Date.now() - state.startedAt),
      penalty_seconds: 0,
      guess_count: 0,
    });
  }

  window.HACKME_GAME_CATALOG = catalog;
  window.HACKME_GAME_MODULES = modules;
  window.HACKME_LOCAL_GAME_HELPERS = { cell, clamp, makeCtx, registerScore };
  window.hackmeGameByKey = byKey;
  window.registerHackmeLocalGameModule = function registerHackmeLocalGameModule(key, module) {
    if (!key || !module?.mount) return;
    modules[key] = module;
  };
}());
