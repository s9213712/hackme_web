'use strict';

(function () {
  const catalog = [
    { key: "chess", title: "西洋棋", subtitle: "玩家對戰 / 電腦練習", legacy: true },
    { key: "sudoku", title: "數獨", subtitle: "單人邏輯解題", legacy: true },
    { key: "minesweeper", title: "踩地雷", subtitle: "單人推理挑戰", legacy: true },
    { key: "1a2b", title: "1A2B", subtitle: "單人猜數字", legacy: true },
    { key: "tetris", title: "俄羅斯方塊", subtitle: "高分消除挑戰", legacy: true },
    { key: "space_shooter", title: "宇宙戰機", subtitle: "高分射擊挑戰", legacy: true },
    { key: "fps_arena", title: "3D 射擊場", subtitle: "3D 射擊訓練 / 合作 / PvP", legacy: true },
    { key: "open_world", title: "都市開放世界", subtitle: "3D 城市探索 / 駕車任務 / 警戒追逐" },
    { key: "bullet_hell", title: "彈幕遊戲", subtitle: "閃避密集彈幕並反擊" },
    { key: "stickman_shooter", title: "火柴人橫向射擊", subtitle: "2D 側捲平台射擊 / 合作解謎" },
    { key: "real_tetris", title: "真實版俄羅斯方塊", subtitle: "剛體物理與 90% 消線" },
    { key: "snake", title: "貪食蛇", subtitle: "滑動或方向鍵控制蛇吃食物" },
    { key: "game_2048", title: "2048", subtitle: "合併數字方塊，挑戰最高分" },
    { key: "brick_breaker", title: "打磚塊", subtitle: "移動擋板反彈球打掉磚塊" },
    { key: "reversi", title: "黑白棋", subtitle: "線上棋盤 / AI 練習" },
    { key: "go", title: "圍棋", subtitle: "19 路線上棋盤，目數/眼位結算" },
    { key: "gomoku", title: "五子棋", subtitle: "15 路線上棋盤，AI 練習 / 雙人對局" },
    { key: "chinese_chess", title: "中國象棋", subtitle: "9x10 線上棋盤，將帥對弈 / AI 練習" },
  ];

  const modules = window.HACKME_GAME_MODULES || {};
  const byKey = (key) => catalog.find((game) => game.key === key) || catalog[0];
  const cell = (value, cls = "") => `<button class="${cls}" type="button">${value || ""}</button>`;
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const achievementStoreKey = "hackme.game.achievements.v1";
  const missionStoreKey = "hackme.game.dailyMissions.v1";
  const replayStoreKey = "hackme.game.replays.v1";
  const clockPresets = [
    { key: "rapid_10_0", label: "Rapid 10+0", mainSeconds: 600, incrementSeconds: 0 },
    { key: "rapid_15_10", label: "Rapid 15+10", mainSeconds: 900, incrementSeconds: 10 },
    { key: "blitz_3_2", label: "Blitz 3+2", mainSeconds: 180, incrementSeconds: 2 },
    { key: "bullet_1_0", label: "Bullet 1+0", mainSeconds: 60, incrementSeconds: 0 },
    { key: "custom", label: "自訂", mainSeconds: 600, incrementSeconds: 0 },
  ];

  function makeCtx(api, title) {
    api.setTitle(title);
    api.setActions(`<button class="btn game-mini-btn btn-primary" type="button" data-action="new">開始</button>`);
  }

  function registerScore(api, score, state, difficulty = "standard") {
    if (!score || score <= 0) return;
    api.submitScore({
      score,
      difficulty,
      puzzle_id: state.dailyChallenge?.key || api.key,
      raw_elapsed_ms: Math.max(1, Date.now() - state.startedAt),
      elapsed_ms: Math.max(1, Date.now() - state.startedAt),
      penalty_seconds: 0,
      guess_count: 0,
      lines: Number(state.lines || 0),
      combo: Number(state.maxCombo || state.combo || 0),
      collapse: Number(state.collapseEvents || 0),
      graze: Number(state.graze || 0),
      wave: Number(state.wave || 0),
      boss: Number(state.bossDefeated || state.boss || 0),
      weapon: Number(state.weaponLevel || state.shotLevel || 0),
      maxTile: Number(state.maxTile || 0),
      moves: Number(state.moves || 0),
      length: Number(state.maxLength || state.snake?.length || 0),
      powerup: Number(state.powerupsCollected || 0),
      multiball: Number(state.multiball || 0),
    });
  }

  function gameUserStorageScope() {
    const id = typeof currentUserId !== "undefined" ? String(currentUserId || "").trim() : "";
    if (id) return `user:${id}`;
    const username = typeof currentUser !== "undefined" ? String(currentUser || "").trim() : "";
    return username ? `user-name:${username}` : "guest";
  }

  function gameUserStorageKey(key) {
    return `hackme:${gameUserStorageScope()}:${key}`;
  }

  function storageGetJson(key, fallback) {
    try {
      const raw = window.localStorage?.getItem(gameUserStorageKey(key));
      return raw ? JSON.parse(raw) : fallback;
    } catch (err) {
      return fallback;
    }
  }

  function storageSetJson(key, value) {
    try {
      window.localStorage?.setItem(gameUserStorageKey(key), JSON.stringify(value));
    } catch (err) {
      // Local storage is optional; games continue without persistent badges.
    }
  }

  function gameUserStorageScope() {
    const id = typeof currentUserId !== "undefined" && currentUserId !== null ? String(currentUserId).trim() : "";
    if (id) return `user:${id}`;
    const username = typeof currentUser !== "undefined" && currentUser ? String(currentUser).trim() : "";
    if (username) return `name:${username.replace(/[^a-zA-Z0-9_.:-]/g, "_").slice(0, 64)}`;
    return "anonymous";
  }

  function gameUserStorageKey(key) {
    return `${key}:${gameUserStorageScope()}`;
  }

  function hashGameString(value) {
    let hash = 2166136261;
    String(value || "").split("").forEach((char) => {
      hash ^= char.charCodeAt(0);
      hash = Math.imul(hash, 16777619);
    });
    return hash >>> 0;
  }

  function createGameSeededRandom(seed) {
    let state = Number(seed || 1) >>> 0;
    return function seededGameRandom() {
      state = (state + 0x6D2B79F5) >>> 0;
      let value = state;
      value = Math.imul(value ^ (value >>> 15), value | 1);
      value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
      return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
    };
  }

  function dailyGameDateKey(date = new Date()) {
    const local = new Date(date.getTime() - (date.getTimezoneOffset() * 60000));
    return local.toISOString().slice(0, 10);
  }

  function dailyChallengeForGame(gameKey, date = new Date()) {
    const day = dailyGameDateKey(date);
    const seed = hashGameString(`${gameKey}:${day}:hackme-daily`);
    const modifiers = [
      { key: "precision", label: "精準日", difficulty: "daily-precision" },
      { key: "rush", label: "衝刺日", difficulty: "daily-rush" },
      { key: "survival", label: "生存日", difficulty: "daily-survival" },
      { key: "combo", label: "連段日", difficulty: "daily-combo" },
    ];
    const modifier = modifiers[seed % modifiers.length];
    return {
      key: `${gameKey}-daily-${day}`,
      gameKey,
      date: day,
      seed,
      label: `每日挑戰 ${day} · ${modifier.label}`,
      modifier: modifier.key,
      difficulty: modifier.difficulty,
    };
  }

  const gameMissionCatalog = {
    sudoku: [
      { id: "daily-complete", label: "完成今日題", target: 1, metric: "complete" },
      { id: "clean-check", label: "錯誤檢查不超過 2 次", target: 1, metric: "clean" },
      { id: "under-8m", label: "8 分鐘內完成", target: 480000, metric: "elapsed_under" },
    ],
    minesweeper: [
      { id: "daily-clear", label: "完成一盤", target: 1, metric: "complete" },
      { id: "flag-discipline", label: "插旗數不超過地雷數", target: 1, metric: "clean" },
      { id: "speed-clear", label: "3 分鐘內完成", target: 180000, metric: "elapsed_under" },
    ],
    "1a2b": [
      { id: "daily-crack", label: "破解一題", target: 1, metric: "complete" },
      { id: "few-guesses", label: "6 次內猜中", target: 6, metric: "guess_under" },
      { id: "under-2m", label: "2 分鐘內完成", target: 120000, metric: "elapsed_under" },
    ],
    tetris: [
      { id: "score-1200", label: "單局 1200 分", target: 1200, metric: "score" },
      { id: "clear-12", label: "消除 12 行", target: 12, metric: "lines" },
      { id: "combo-3", label: "達成 Combo x3", target: 3, metric: "combo" },
    ],
    real_tetris: [
      { id: "physics-600", label: "物理版 600 分", target: 600, metric: "score" },
      { id: "collapse-2", label: "觸發 2 次倒塌", target: 2, metric: "collapse" },
      { id: "line-2", label: "90% 消線 2 行", target: 2, metric: "lines" },
    ],
    space_shooter: [
      { id: "score-1500", label: "出擊 1500 分", target: 1500, metric: "score" },
      { id: "boss", label: "擊破 Boss", target: 1, metric: "boss" },
      { id: "weapon-4", label: "武器升到 4 級", target: 4, metric: "weapon" },
    ],
    fps_arena: [
      { id: "score-1800", label: "任務 1800 分", target: 1800, metric: "score" },
      { id: "accuracy-45", label: "命中率 45%", target: 45, metric: "accuracy" },
      { id: "survive", label: "任務結束仍存活", target: 1, metric: "survive" },
    ],
    open_world: [
      { id: "score-2500", label: "城市分數 2500", target: 2500, metric: "score" },
      { id: "missions-2", label: "完成 2 個城市任務", target: 2, metric: "missions" },
      { id: "evade", label: "甩開一次追逐", target: 1, metric: "evasion" },
    ],
    bullet_hell: [
      { id: "score-1800", label: "彈幕 1800 分", target: 1800, metric: "score" },
      { id: "graze-40", label: "擦彈 40 次", target: 40, metric: "graze" },
      { id: "wave-5", label: "抵達第 5 波", target: 5, metric: "wave" },
    ],
    stickman_shooter: [
      { id: "score-1600", label: "火柴人 1600 分", target: 1600, metric: "score" },
      { id: "boss", label: "擊破側捲 Boss", target: 1, metric: "boss" },
      { id: "accuracy-40", label: "命中率 40%", target: 40, metric: "accuracy" },
    ],
    snake: [
      { id: "score-120", label: "貪食蛇 120 分", target: 120, metric: "score" },
      { id: "length-12", label: "長度 12", target: 12, metric: "length" },
      { id: "powerup", label: "吃到道具", target: 1, metric: "powerup" },
    ],
    game_2048: [
      { id: "score-1500", label: "2048 得 1500 分", target: 1500, metric: "score" },
      { id: "tile-512", label: "合出 512", target: 512, metric: "maxTile" },
      { id: "limited", label: "限步模式完成 60 步", target: 60, metric: "moves" },
    ],
    brick_breaker: [
      { id: "score-900", label: "打磚塊 900 分", target: 900, metric: "score" },
      { id: "boss-brick", label: "擊破 Boss 磚", target: 1, metric: "boss" },
      { id: "multiball", label: "啟動多球", target: 1, metric: "multiball" },
    ],
    reversi: [
      { id: "corner", label: "佔領角落", target: 1, metric: "corner" },
      { id: "win-ai", label: "擊敗 AI", target: 1, metric: "win_ai" },
      { id: "score-360", label: "黑白棋 360 分", target: 360, metric: "score" },
    ],
    go: [
      { id: "capture", label: "圍棋吃子", target: 1, metric: "capture" },
      { id: "territory", label: "地盤估算領先", target: 1, metric: "territory" },
      { id: "score-240", label: "圍棋 240 分", target: 240, metric: "score" },
    ],
    gomoku: [
      { id: "open-four", label: "形成活四", target: 1, metric: "open_four" },
      { id: "win", label: "五子連線勝", target: 1, metric: "win" },
      { id: "score-260", label: "五子棋 260 分", target: 260, metric: "score" },
    ],
    chinese_chess: [
      { id: "win", label: "中國象棋勝局", target: 1, metric: "win" },
      { id: "capture-5", label: "吃子 5 枚", target: 5, metric: "capture" },
      { id: "score-1200", label: "象棋 1200 分", target: 1200, metric: "score" },
    ],
  };

  const achievementCatalog = {
    sudoku: [
      ["first-solve", "數獨初解", "完成一題數獨。"],
      ["note-master", "筆記整理", "使用筆記模式完成一題。"],
      ["no-mistake", "零錯誤完成", "不觸發錯誤檢查完成數獨。"],
    ],
    minesweeper: [
      ["first-clear", "安全拆雷", "完成一盤踩地雷。"],
      ["master-clear", "大師拆雷", "完成大師難度。"],
      ["speed-clear", "快速排雷", "3 分鐘內完成。"],
    ],
    "1a2b": [
      ["quick-crack", "快速破譯", "2 分鐘內完成。"],
      ["few-guesses", "精準猜測", "6 次內完成。"],
      ["hint-win", "提示取捨", "使用提示後仍完成。"],
    ],
    tetris: [
      ["hold-used", "戰術 Hold", "使用 Hold 保留一塊方塊。"],
      ["tetris-clear", "四行消除", "一次消除四行。"],
      ["back-to-back", "Back-to-Back", "連續兩次四行消除。"],
      ["combo-chain", "連續消除", "連續 3 次落子都有消行。"],
      ["score-posted", "方塊上榜", "完成一局並送出分數。"],
    ],
    real_tetris: [
      ["collapse", "重心崩塌", "堆疊重心失衡造成倒塌。"],
      ["physics-line", "物理消線", "真實物理中完成消線。"],
      ["root-tuned", "調參沙盒", "root 調整物理參數。"],
    ],
    space_shooter: [
      ["score-posted", "完成出擊", "完成一局宇宙戰機。"],
      ["boss-down", "旗艦擊破", "擊破宇宙戰機 Boss。"],
      ["weapon-max", "滿載火力", "宇宙戰機武器升級到最高階。"],
      ["shield-save", "護盾救援", "用護盾擋下一次傷害。"],
    ],
    fps_arena: [
      ["headshot", "爆頭訓練", "命中頭部。"],
      ["defuse", "拆彈成功", "完成 Bomb Defuse。"],
      ["accuracy", "穩定射手", "命中率達 45%。"],
    ],
    open_world: [
      ["first-drive", "城市駕駛", "第一次進入車輛。"],
      ["city-runner", "城市跑者", "同一局完成三個城市任務。"],
      ["clean-escape", "甩開追逐", "成功降低警戒並脫離追逐。"],
    ],
    bullet_hell: [
      ["score-posted", "彈幕出擊", "完成一局彈幕挑戰。"],
      ["max-power", "彈幕滿火力", "取得火力升級到最高階。"],
      ["wave-five", "第五波生還", "撐到第 5 波彈幕。"],
      ["boss-down", "Boss 擊破", "擊破彈幕 Boss。"],
    ],
    stickman_shooter: [
      ["first-clear", "火柴人出擊", "完成一局側捲射擊。"],
      ["boss-down", "側捲 Boss 擊破", "擊破關卡 Boss。"],
      ["reload-discipline", "冷靜換彈", "彈匣耗盡後完成換彈。"],
    ],
    snake: [
      ["powerup", "道具吞食", "吃到任務道具。"],
      ["long-snake", "長蛇成形", "長度達 12。"],
      ["speed-zone", "加速區生還", "穿越加速區後繼續得分。"],
    ],
    game_2048: [
      ["tile-512", "512 里程碑", "合成 512。"],
      ["undo-used", "戰術撤銷", "使用撤銷仍繼續挑戰。"],
      ["obstacle-win", "障礙挑戰", "障礙模式達成 1024。"],
    ],
    brick_breaker: [
      ["multiball", "多球開局", "啟動多球。"],
      ["boss-brick", "Boss 磚擊破", "擊破 Boss 磚。"],
      ["shield-save", "護盾救球", "用護盾擋下一次漏球。"],
    ],
    reversi: [
      ["corner", "角落意識", "佔領至少一個角落。"],
      ["beat-ai", "黑白棋勝 AI", "擊敗電腦。"],
    ],
    go: [
      ["capture", "吃子入門", "圍棋吃掉對方棋子。"],
      ["territory", "地盤判讀", "地盤估算領先。"],
    ],
    gomoku: [
      ["threat", "威脅建構", "形成活四或直接勝手。"],
      ["renju-clean", "禁手自律", "連珠規則下避免禁手。"],
    ],
    chinese_chess: [
      ["xiangqi-win", "象棋勝局", "完成一局中國象棋並獲勝。"],
      ["xiangqi-cannon", "炮打隔山", "用炮吃子。"],
      ["mission-win", "每日任務：中國象棋勝局", "完成中國象棋勝局任務。"],
    ],
  };

  const aiStrengthCatalog = {
    reversi: {
      easy: "約入門玩家；能吃子但常放角落。",
      normal: "約初級玩家；3-ply alpha-beta，具角落、行動力與 frontier 意識。",
      hard: "約中級休閒玩家；4-ply 穩定邊角搜尋、transposition cache 與終盤 exact solve。",
    },
    go: {
      easy: "19 路入門約 25-20 kyu；重氣、眼位與基本地盤。",
      normal: "19 路初級約 20-15 kyu；短 rollout 評估目數。",
      hard: "19 路初中級約 12-8 kyu；完整死活網路評估叫吃、雙眼、假眼、連接、切斷與攻殺。",
      katago: "KataGo 神經網路；使用本機 KataGo analysis engine 與模型，強度取決於設定的模型與 visits。",
    },
    gomoku: {
      easy: "約入門；會找鄰近點與立即勝。",
      normal: "約初中級；會擋五、活四與雙勝點。",
      hard: "約中級以上；threat-space + 2-ply alpha-beta，會處理活四、雙活三與對手威脅封鎖。",
    },
    chinese_chess: {
      easy: "約入門；會吃高價子與避免明顯將死。",
      normal: "約初級；懂將軍、將帥照面與基本子力。",
      hard: "約初中級；會避開被白吃並優先製造將軍。",
    },
    chess: {
      "experiment 0:minimax2ply": "2 層物質 minimax；先看自己這步物質再看對手最佳回應。",
      "experiment 1:search": "引擎搜尋 + 對局學習；舊名 experiment。",
      "experiment 2:nn": "NN 評估；auto-retrain 斷開，僅紀錄不再線上更新。",
      "experiment 3:dl": "DL 語義平衡實驗；偏研究模型。auto-retrain 斷開。",
      "experiment 4:pv": "Policy/Value + MCTS 實驗；有候選策略。auto-retrain 斷開。",
      "experiment 5:nnue": "NNUE + AlphaBeta/PVS；目前最有潛力但仍需實戰 gate。",
      "experiment 6:neuralnet": "Neural Network (Exp6)；3 層 NNUE-style 真實神經網路 + 增量累加器，需訓練後才有實戰強度。",
      // legacy labels for old DB rows
      normal: "舊版「普通」(legacy)。",
      hard: "舊版「困難」(legacy)，現為 experiment 0:minimax2ply。",
      experiment: "舊版「實驗」(legacy)，現為 experiment 1:search。",
      stockfish: "Stockfish 本機外部引擎；只在 server 偵測到本機 binary 時顯示。",
    },
  };

  function missionStoreDayKey(gameKey, day) {
    return `${gameKey}:${day}`;
  }

  function dailyMissionsForGame(gameKey, challenge = dailyChallengeForGame(gameKey)) {
    const base = gameMissionCatalog[gameKey] || [
      { id: "daily-play", label: "完成今日挑戰", target: 1, metric: "complete" },
      { id: "daily-score", label: "刷新分數", target: 500, metric: "score" },
      { id: "daily-focus", label: "保持 2 分鐘", target: 120000, metric: "elapsed_over" },
    ];
    return base.map((mission, index) => ({
      ...mission,
      key: `${challenge?.key || gameKey}:${mission.id}`,
      dailyIndex: index + 1,
      progress: 0,
      complete: false,
    }));
  }

  function missionProgressValue(mission, result = {}) {
    if (mission.metric === "complete") return result.completed === false ? 0 : 1;
    if (mission.metric === "clean") return result.clean ? 1 : 0;
    if (mission.metric === "elapsed_under") {
      const elapsed = Number(result.elapsed_ms || result.elapsed || 0);
      return elapsed > 0 && elapsed <= Number(mission.target) ? Number(mission.target) : 0;
    }
    if (mission.metric === "elapsed_over") return Number(result.elapsed_ms || result.elapsed || 0);
    if (mission.metric === "guess_under") {
      const guesses = Number(result.guess_count || result.guesses || 0);
      return guesses > 0 && guesses <= Number(mission.target) ? Number(mission.target) : 0;
    }
    if (mission.metric === "accuracy") return Number(result.accuracy || 0);
    return Number(result[mission.metric] || 0);
  }

  function listGameDailyMissions(gameKey, challenge = dailyChallengeForGame(gameKey)) {
    const store = storageGetJson(missionStoreKey, {});
    const dayKey = missionStoreDayKey(gameKey, challenge?.date || dailyGameDateKey());
    const saved = store[dayKey] || {};
    return dailyMissionsForGame(gameKey, challenge).map((mission) => {
      const row = saved[mission.id] || {};
      return {
        ...mission,
        progress: Number(row.progress || 0),
        complete: Boolean(row.complete),
        completedAt: row.completedAt || "",
      };
    });
  }

  function recordGameMissionProgress(gameKey, id, progress, target, label = "") {
    const challenge = dailyChallengeForGame(gameKey);
    const store = storageGetJson(missionStoreKey, {});
    const dayKey = missionStoreDayKey(gameKey, challenge.date);
    const day = store[dayKey] || {};
    const old = day[id] || {};
    const nextProgress = Math.max(Number(old.progress || 0), Number(progress || 0));
    const complete = Boolean(old.complete) || nextProgress >= Number(target || 1);
    day[id] = {
      id,
      userScope: gameUserStorageScope(),
      label: label || old.label || id,
      progress: nextProgress,
      target: Number(target || old.target || 1),
      complete,
      completedAt: complete ? (old.completedAt || new Date().toISOString()) : "",
    };
    store[dayKey] = day;
    storageSetJson(missionStoreKey, store);
    if (complete && !old.complete) {
      recordGameAchievement(gameKey, `mission-${id}`, `每日任務：${label || id}`, challenge.label);
    }
    return day[id];
  }

  function completeGameMissionsForResult(gameKey, result = {}) {
    const challenge = dailyChallengeForGame(gameKey);
    return listGameDailyMissions(gameKey, challenge).map((mission) => {
      const progress = missionProgressValue(mission, result);
      return recordGameMissionProgress(gameKey, mission.id, progress, mission.target, mission.label);
    });
  }

  function recordGameAchievement(gameKey, id, label, detail = "") {
    if (!gameKey || !id) return { unlocked: false };
    const store = storageGetJson(achievementStoreKey, {});
    const key = `${gameKey}:${id}`;
    if (store[key]) return { unlocked: false, ...store[key] };
    const row = {
      key,
      userScope: gameUserStorageScope(),
      gameKey,
      id,
      label: label || id,
      detail: detail || "",
      unlockedAt: new Date().toISOString(),
    };
    store[key] = row;
    storageSetJson(achievementStoreKey, store);
    return { unlocked: true, ...row };
  }

  function listGameAchievements(gameKey = "") {
    const store = storageGetJson(achievementStoreKey, {});
    const unlocked = Object.values(store).filter((row) => !gameKey || row.gameKey === gameKey);
    if (!gameKey || !achievementCatalog[gameKey]) return unlocked;
    const byId = new Map(unlocked.map((row) => [row.id, row]));
    const defined = achievementCatalog[gameKey].map(([id, label, detail]) => ({
      key: `${gameKey}:${id}`,
      gameKey,
      id,
      label,
      detail,
      unlocked: Boolean(byId.get(id)),
      unlockedAt: byId.get(id)?.unlockedAt || "",
    }));
    const extra = unlocked.filter((row) => !defined.some((item) => item.id === row.id));
    return defined.concat(extra.map((row) => ({ ...row, unlocked: true })));
  }

  function recordGameReplay(gameKey, payload = {}) {
    if (!gameKey) return null;
    const store = storageGetJson(replayStoreKey, {});
    const rows = Array.isArray(store[gameKey]) ? store[gameKey] : [];
    const row = {
      id: `${gameKey}-${Date.now()}-${Math.floor(Math.random() * 10000)}`,
      userScope: gameUserStorageScope(),
      gameKey,
      title: payload.title || (byKey(gameKey)?.title || gameKey),
      score: Number(payload.score || 0),
      summary: payload.summary || "",
      difficulty: payload.difficulty || "standard",
      puzzleId: payload.puzzle_id || payload.puzzleId || "",
      elapsedMs: Number(payload.elapsed_ms || payload.elapsedMs || 0),
      moves: Array.isArray(payload.moves) ? payload.moves.slice(-80) : [],
      createdAt: new Date().toISOString(),
    };
    rows.unshift(row);
    store[gameKey] = rows.slice(0, 8);
    storageSetJson(replayStoreKey, store);
    return row;
  }

  function listGameReplays(gameKey = "") {
    const store = storageGetJson(replayStoreKey, {});
    if (gameKey) return Array.isArray(store[gameKey]) ? store[gameKey] : [];
    return Object.values(store).flatMap((rows) => Array.isArray(rows) ? rows : []);
  }

  function buildGameShareText(gameKey, result = {}) {
    const game = byKey(gameKey);
    const score = Number(result.score || 0).toLocaleString();
    const difficulty = result.difficulty || "standard";
    const elapsed = Number(result.elapsed_ms || result.elapsedMs || 0);
    const time = elapsed > 0 && window.formatSoloGameTime ? ` · ${window.formatSoloGameTime(elapsed)}` : "";
    return `${game?.title || gameKey}｜${difficulty}｜分數 ${score}${time}`;
  }

  function gameClockPreset(key) {
    return clockPresets.find((preset) => preset.key === key) || clockPresets[0];
  }

  function formatGameClock(ms) {
    const safeMs = Math.max(0, Math.ceil(Number(ms || 0) / 1000) * 1000);
    const totalSeconds = Math.ceil(safeMs / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function createCompetitionClock(options = {}) {
    const preset = gameClockPreset(options.presetKey || "rapid_10_0");
    const state = {
      enabled: false,
      presetKey: preset.key,
      mainSeconds: preset.mainSeconds,
      incrementSeconds: preset.incrementSeconds,
      whiteMs: preset.mainSeconds * 1000,
      blackMs: preset.mainSeconds * 1000,
      activeSide: "black",
      running: false,
      expiredSide: "",
      lastTick: 0,
    };
    let timer = null;
    const subscribers = new Set();
    const notify = () => subscribers.forEach((fn) => fn({ ...state }));
    const stop = () => {
      if (timer) clearInterval(timer);
      timer = null;
      state.running = false;
      state.lastTick = 0;
      notify();
    };
    const tick = () => {
      if (!state.enabled || !state.running || state.expiredSide) return;
      const now = performance.now();
      if (!state.lastTick) state.lastTick = now;
      const delta = Math.max(0, now - state.lastTick);
      state.lastTick = now;
      const key = state.activeSide === "white" ? "whiteMs" : "blackMs";
      state[key] = Math.max(0, state[key] - delta);
      if (state[key] <= 0) {
        state.expiredSide = state.activeSide;
        state.running = false;
        if (timer) clearInterval(timer);
        timer = null;
        options.onExpire?.(state.activeSide, { ...state });
      }
      notify();
    };
    const start = (side = state.activeSide) => {
      state.activeSide = side === "white" ? "white" : "black";
      if (!state.enabled || state.expiredSide) {
        notify();
        return;
      }
      state.running = true;
      state.lastTick = performance.now();
      if (!timer) timer = setInterval(tick, 250);
      notify();
    };
    const reset = (side = "black") => {
      if (timer) clearInterval(timer);
      timer = null;
      state.whiteMs = state.mainSeconds * 1000;
      state.blackMs = state.mainSeconds * 1000;
      state.activeSide = side === "white" ? "white" : "black";
      state.expiredSide = "";
      state.running = false;
      state.lastTick = 0;
      if (state.enabled) start(state.activeSide);
      else notify();
    };
    const configure = (config = {}) => {
      if (typeof config.enabled === "boolean") state.enabled = config.enabled;
      if (config.presetKey) state.presetKey = config.presetKey;
      if (Number.isFinite(Number(config.mainSeconds))) state.mainSeconds = Math.max(10, Number(config.mainSeconds));
      if (Number.isFinite(Number(config.incrementSeconds))) state.incrementSeconds = Math.max(0, Number(config.incrementSeconds));
      notify();
    };
    const switchTurn = (nextSide) => {
      if (!state.enabled || state.expiredSide) {
        state.activeSide = nextSide === "white" ? "white" : "black";
        notify();
        return;
      }
      tick();
      const oldKey = state.activeSide === "white" ? "whiteMs" : "blackMs";
      state[oldKey] += state.incrementSeconds * 1000;
      start(nextSide);
    };
    return {
      state,
      configure,
      reset,
      start,
      stop,
      switchTurn,
      tick,
      subscribe(fn) {
        subscribers.add(fn);
        fn({ ...state });
        return () => subscribers.delete(fn);
      },
      snapshot() {
        tick();
        return { ...state };
      },
    };
  }

  window.HACKME_GAME_CATALOG = catalog;
  window.HACKME_GAME_MODULES = modules;
  window.HACKME_GAME_CLOCK_PRESETS = clockPresets;
  window.formatHackmeGameClock = formatGameClock;
  window.gameClockPreset = gameClockPreset;
  window.createHackmeCompetitionClock = createCompetitionClock;
  window.hackmeGameDailyChallenge = dailyChallengeForGame;
  window.createHackmeGameSeededRandom = createGameSeededRandom;
  window.recordHackmeGameAchievement = recordGameAchievement;
  window.listHackmeGameAchievements = listGameAchievements;
  window.HACKME_GAME_AI_STRENGTH = aiStrengthCatalog;
  window.hackmeGameDailyMissions = dailyMissionsForGame;
  window.listHackmeGameDailyMissions = listGameDailyMissions;
  window.recordHackmeGameMissionProgress = recordGameMissionProgress;
  window.completeHackmeGameMissionsForResult = completeGameMissionsForResult;
  window.recordHackmeGameReplay = recordGameReplay;
  window.listHackmeGameReplays = listGameReplays;
  window.buildHackmeGameShareText = buildGameShareText;
  window.HACKME_LOCAL_GAME_HELPERS = {
    cell,
    clamp,
    makeCtx,
    registerScore,
    clockPresets,
    gameClockPreset,
    formatGameClock,
    createCompetitionClock,
    dailyChallengeForGame,
    createGameSeededRandom,
    recordGameAchievement,
    listGameAchievements,
    dailyMissionsForGame,
    listGameDailyMissions,
    recordGameMissionProgress,
    completeGameMissionsForResult,
    recordGameReplay,
    listGameReplays,
    buildGameShareText,
    gameUserStorageScope,
    gameUserStorageKey,
    userScope: gameUserStorageScope(),
  };
  window.hackmeGameByKey = byKey;
  window.registerHackmeLocalGameModule = function registerHackmeLocalGameModule(key, module) {
    if (!key || !module?.mount) return;
    modules[key] = module;
  };
}());
