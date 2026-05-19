'use strict';

(function () {
  const { makeCtx, registerScore, clamp } = window.HACKME_LOCAL_GAME_HELPERS;
  const WIDTH = 360;
  const HEIGHT = 480;
  const HORIZON_Y = 76;
  const PLAYER_Y = 388;
  const LANES = [-1, 0, 1];
  const START_COUNTDOWN_TICKS = 92;
  const MAX_TRAFFIC_CARS = 8;
  const TRAFFIC_MIN_SCREEN_GAP = 66;
  const PLAYER_CAR_WIDTH = 46;
  const PLAYER_CAR_HEIGHT = 76;
  const ROAD_EDGE_MARGIN = 26;
  const EDGE_IMPACT_COOLDOWN = 24;
  const CAR_COLORS = ["#ef4444", "#f59e0b", "#22c55e", "#38bdf8", "#a78bfa"];
  const PICKUP_DETAILS = {
    nitro: { label: "N", color: "#22d3ee", name: "氮氣補給" },
    boost: { label: "B", color: "#facc15", name: "加速道具" },
    jammer: { label: "J", color: "#c084fc", name: "干擾器" },
    oil: { label: "O", color: "#fb923c", name: "油漬干擾" },
    shield: { label: "S", color: "#34d399", name: "護盾" },
  };

  function racingRandom(state) {
    return typeof state.rng === "function" ? state.rng() : Math.random();
  }

  function roadT(y) {
    return clamp((y - HORIZON_Y) / (HEIGHT - HORIZON_Y), 0, 1);
  }

  function roadWidthAt(y) {
    const t = roadT(y);
    return 92 + t * t * 250;
  }

  function roadCenterAt(y, state) {
    const t = roadT(y);
    return WIDTH / 2 + Number(state.curve || 0) * 72 * t * t + Math.sin(state.distance / 520 + t * 5.2) * 10 * t;
  }

  function laneX(lane, y, state) {
    return roadCenterAt(y, state) + lane * roadWidthAt(y) * 0.245;
  }

  function roadBoundsAt(y, state) {
    const center = roadCenterAt(y, state);
    const width = roadWidthAt(y);
    return {
      left: center - width / 2 + ROAD_EDGE_MARGIN,
      right: center + width / 2 - ROAD_EDGE_MARGIN,
      center,
      width,
    };
  }

  function racingRect(x, y, w, h) {
    return { left: x - w / 2, right: x + w / 2, top: y - h / 2, bottom: y + h / 2, width: w, height: h };
  }

  function racingRectsOverlap(a, b) {
    return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  }

  function trafficCarSize(y) {
    const t = roadT(y);
    return { width: 22 + t * 23, height: 34 + t * 38 };
  }

  function trafficLane(car) {
    return Number(car.lane || 0) + Number(car.laneOffset || 0);
  }

  function trafficScreenX(car, state) {
    return laneX(trafficLane(car), car.y, state);
  }

  function trafficCollisionBox(car, state) {
    const size = trafficCarSize(car.y);
    return racingRect(trafficScreenX(car, state), car.y, size.width * 0.82, size.height * 0.82);
  }

  function playerCollisionBox(state) {
    return racingRect(state.playerX, PLAYER_Y, PLAYER_CAR_WIDTH * 0.72, PLAYER_CAR_HEIGHT * 0.78);
  }

  function trafficLaneIsClear(state, lane, y, minGap = TRAFFIC_MIN_SCREEN_GAP) {
    return !(state.traffic || []).some((car) => Math.abs(Number(car.lane || 0) - lane) < 0.45 && Math.abs(Number(car.y || 0) - y) < minGap);
  }

  function chooseTrafficLane(state, y = HORIZON_Y + 12) {
    const lanes = LANES.map((lane) => ({
      lane,
      nearest: Math.min(...(state.traffic || [])
        .filter((car) => Math.abs(Number(car.lane || 0) - lane) < 0.45)
        .map((car) => Math.abs(Number(car.y || 0) - y))
        .concat([999])),
    })).sort((a, b) => b.nearest - a.nearest);
    const open = lanes.filter((row) => row.nearest >= TRAFFIC_MIN_SCREEN_GAP + 14);
    if (!open.length) return null;
    return open[Math.floor(racingRandom(state) * open.length)]?.lane ?? open[0].lane;
  }

  function choosePickupLane(state, y = HORIZON_Y + 10) {
    const open = LANES.filter((lane) => trafficLaneIsClear(state, lane, y, 96));
    const lanes = open.length ? open : LANES;
    return lanes[Math.floor(racingRandom(state) * lanes.length)] || 0;
  }

  function addRacingImpactParticles(state, x, y, color = "#facc15", count = 10) {
    for (let i = 0; i < count; i += 1) {
      const angle = racingRandom(state) * Math.PI * 2;
      const speed = 1.2 + racingRandom(state) * 3.2;
      state.impactParticles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 0.8,
        life: 24 + Math.floor(racingRandom(state) * 16),
        color,
      });
    }
  }

  function drawRacingImpactParticles(ctx, state) {
    (state.impactParticles || []).forEach((particle) => {
      ctx.save();
      ctx.globalAlpha = clamp(particle.life / 34, 0, 1);
      ctx.fillStyle = particle.color || "#facc15";
      ctx.beginPath();
      ctx.arc(particle.x, particle.y, 2.2, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    });
  }

  function drawRacingCar(ctx, x, y, w, h, color, accent = "#e5e7eb", rotation = 0) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(rotation);
    ctx.fillStyle = "rgba(0,0,0,.26)";
    ctx.beginPath();
    ctx.ellipse(0, h * 0.32, w * 0.52, h * 0.2, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(0, -h * 0.5);
    ctx.lineTo(w * 0.44, -h * 0.18);
    ctx.lineTo(w * 0.36, h * 0.42);
    ctx.lineTo(-w * 0.36, h * 0.42);
    ctx.lineTo(-w * 0.44, -h * 0.18);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = accent;
    ctx.fillRect(-w * 0.2, -h * 0.28, w * 0.4, h * 0.22);
    ctx.fillStyle = "rgba(15,23,42,.42)";
    ctx.fillRect(-w * 0.28, h * 0.08, w * 0.56, h * 0.12);
    ctx.fillStyle = "#111827";
    ctx.fillRect(-w * 0.48, -h * 0.2, w * 0.12, h * 0.28);
    ctx.fillRect(w * 0.36, -h * 0.2, w * 0.12, h * 0.28);
    ctx.fillRect(-w * 0.44, h * 0.22, w * 0.12, h * 0.24);
    ctx.fillRect(w * 0.32, h * 0.22, w * 0.12, h * 0.24);
    ctx.restore();
  }

  function pickupDetail(type) {
    return PICKUP_DETAILS[type] || PICKUP_DETAILS.nitro;
  }

  function drawRacingPickup(ctx, state, pickup) {
    const t = roadT(pickup.y);
    const detail = pickupDetail(pickup.type);
    const x = laneX(pickup.lane, pickup.y, state);
    const radius = 17 * t + 6;
    ctx.fillStyle = `${detail.color}40`;
    ctx.beginPath();
    ctx.arc(x, pickup.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = detail.color;
    ctx.beginPath();
    ctx.arc(x, pickup.y, Math.max(7, radius * 0.52), 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#0f172a";
    ctx.font = `700 ${Math.max(9, 11 + t * 6)}px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(detail.label, x, pickup.y + 0.5);
    ctx.textAlign = "start";
    ctx.textBaseline = "alphabetic";
  }

  function drawRacingSkidMarks(ctx, state) {
    (state.skidMarks || []).forEach((mark) => {
      ctx.save();
      ctx.globalAlpha = Math.max(0, Math.min(0.6, mark.alpha || 0));
      ctx.strokeStyle = "#111827";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(mark.x - 9, mark.y);
      ctx.lineTo(mark.x - 2 + mark.lean * 10, mark.y + 20);
      ctx.moveTo(mark.x + 9, mark.y);
      ctx.lineTo(mark.x + 2 + mark.lean * 10, mark.y + 20);
      ctx.stroke();
      ctx.restore();
    });
  }

  function drawRacingOilSlicks(ctx, state) {
    (state.oilSlicks || []).forEach((slick) => {
      ctx.save();
      ctx.globalAlpha = Math.max(0, Math.min(0.55, slick.life / 150));
      ctx.fillStyle = "#111827";
      ctx.beginPath();
      ctx.ellipse(slick.x, slick.y, 24, 9, 0.1, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#fb923c";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.ellipse(slick.x, slick.y, 18, 6, -0.2, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    });
  }

  function drawRacingBackdrop(ctx, state) {
    const sky = ctx.createLinearGradient(0, 0, 0, HEIGHT);
    sky.addColorStop(0, "#7dd3fc");
    sky.addColorStop(0.45, "#bae6fd");
    sky.addColorStop(0.46, "#4ade80");
    sky.addColorStop(1, "#166534");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, WIDTH, HEIGHT);

    ctx.fillStyle = "rgba(15,23,42,.18)";
    for (let i = 0; i < 7; i += 1) {
      const x = (i * 76 - (state.distance * 0.12) % 76) - 28;
      ctx.beginPath();
      ctx.moveTo(x, HORIZON_Y + 18);
      ctx.lineTo(x + 42, HORIZON_Y - 28 - (i % 2) * 12);
      ctx.lineTo(x + 92, HORIZON_Y + 18);
      ctx.closePath();
      ctx.fill();
    }

    const topCenter = roadCenterAt(HORIZON_Y, state);
    const bottomCenter = roadCenterAt(HEIGHT, state);
    ctx.fillStyle = "#1f2937";
    ctx.beginPath();
    ctx.moveTo(topCenter - roadWidthAt(HORIZON_Y) / 2, HORIZON_Y);
    ctx.lineTo(topCenter + roadWidthAt(HORIZON_Y) / 2, HORIZON_Y);
    ctx.lineTo(bottomCenter + roadWidthAt(HEIGHT) / 2, HEIGHT);
    ctx.lineTo(bottomCenter - roadWidthAt(HEIGHT) / 2, HEIGHT);
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = "#dc2626";
    ctx.lineWidth = 9;
    ctx.beginPath();
    ctx.moveTo(topCenter - roadWidthAt(HORIZON_Y) / 2 + 7, HORIZON_Y);
    ctx.lineTo(bottomCenter - roadWidthAt(HEIGHT) / 2 + 21, HEIGHT);
    ctx.moveTo(topCenter + roadWidthAt(HORIZON_Y) / 2 - 7, HORIZON_Y);
    ctx.lineTo(bottomCenter + roadWidthAt(HEIGHT) / 2 - 21, HEIGHT);
    ctx.stroke();
    ctx.strokeStyle = "#f8fafc";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(topCenter - roadWidthAt(HORIZON_Y) / 2 + 12, HORIZON_Y);
    ctx.lineTo(bottomCenter - roadWidthAt(HEIGHT) / 2 + ROAD_EDGE_MARGIN, HEIGHT);
    ctx.moveTo(topCenter + roadWidthAt(HORIZON_Y) / 2 - 12, HORIZON_Y);
    ctx.lineTo(bottomCenter + roadWidthAt(HEIGHT) / 2 - ROAD_EDGE_MARGIN, HEIGHT);
    ctx.stroke();

    ctx.strokeStyle = "#f8fafc";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(topCenter - roadWidthAt(HORIZON_Y) / 2, HORIZON_Y);
    ctx.lineTo(bottomCenter - roadWidthAt(HEIGHT) / 2, HEIGHT);
    ctx.moveTo(topCenter + roadWidthAt(HORIZON_Y) / 2, HORIZON_Y);
    ctx.lineTo(bottomCenter + roadWidthAt(HEIGHT) / 2, HEIGHT);
    ctx.stroke();

    ctx.strokeStyle = "rgba(248,250,252,.78)";
    ctx.lineWidth = 3;
    for (const lane of [-0.5, 0.5]) {
      for (let y = HORIZON_Y + 14 - (state.distance * 0.38) % 42; y < HEIGHT; y += 42) {
        const y2 = Math.min(HEIGHT, y + 20 * roadT(y));
        ctx.beginPath();
        ctx.moveTo(laneX(lane, y, state), y);
        ctx.lineTo(laneX(lane, y2, state), y2);
        ctx.stroke();
      }
    }

    ctx.fillStyle = "rgba(250,204,21,.78)";
    for (let y = HORIZON_Y + 22 - (state.distance * 0.18) % 64; y < HEIGHT; y += 64) {
      const width = roadWidthAt(y);
      ctx.fillRect(roadCenterAt(y, state) - width * 0.58, y, 12 * roadT(y), 5);
      ctx.fillRect(roadCenterAt(y, state) + width * 0.54, y, 12 * roadT(y), 5);
    }
  }

  function drawRacingHud(ctx, state) {
    ctx.fillStyle = "rgba(15,23,42,.72)";
    ctx.fillRect(10, 10, 340, 48);
    ctx.fillStyle = "#e5e7eb";
    ctx.font = "700 15px system-ui, sans-serif";
    ctx.fillText(`分數 ${Math.max(0, Math.round(state.score || 0)).toLocaleString()}`, 20, 30);
    ctx.fillText(`速度 ${Math.round(state.speed || 0)}`, 146, 30);
    ctx.fillText(`車況 ${Math.round(state.integrity || 0)}%`, 252, 30);
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`距離 ${Math.floor(state.distance || 0)} / ${state.trackLength} · 超車 ${state.overtakes || 0} · 甩尾 ${Math.round(state.driftScore || 0)}`, 20, 50);
  }

  function drawRacingMinimap(ctx, state) {
    const x = 284;
    const y = 66;
    const w = 58;
    const h = 118;
    ctx.fillStyle = "rgba(15,23,42,.72)";
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = "rgba(226,232,240,.7)";
    ctx.lineWidth = 2;
    ctx.strokeRect(x + 7, y + 10, w - 14, h - 20);
    ctx.strokeStyle = "rgba(148,163,184,.58)";
    ctx.beginPath();
    ctx.moveTo(x + w / 2, y + 14);
    ctx.bezierCurveTo(x + 16, y + 38, x + w - 14, y + 76, x + w / 2, y + h - 14);
    ctx.stroke();
    const progress = clamp((state.distance || 0) / Math.max(1, state.trackLength || 1), 0, 1);
    const playerY = y + h - 15 - progress * (h - 30);
    ctx.fillStyle = "#ef4444";
    ctx.beginPath();
    ctx.arc(x + w / 2 + Number(state.curve || 0) * 5, playerY, 4.5, 0, Math.PI * 2);
    ctx.fill();
    (state.traffic || []).slice(0, 7).forEach((car) => {
      const relative = clamp((PLAYER_Y - car.y + 120) / 310, 0, 1);
      ctx.fillStyle = car.disrupted ? "#c084fc" : "#f8fafc";
      ctx.fillRect(x + w / 2 + car.lane * 11 - 2, playerY - relative * 56 - 2, 4, 4);
    });
    (state.pickups || []).slice(0, 5).forEach((pickup) => {
      const relative = clamp((PLAYER_Y - pickup.y + 120) / 330, 0, 1);
      ctx.fillStyle = pickupDetail(pickup.type).color;
      ctx.fillRect(x + w / 2 + pickup.lane * 11 - 1.5, playerY - relative * 62 - 1.5, 3, 3);
    });
  }

  function drawRacingSteeringWheel(ctx, state, cx, cy, radius) {
    const angle = Number(state.steeringAngle || 0);
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(angle);
    ctx.strokeStyle = "#e5e7eb";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(0, 0, radius, 0, Math.PI * 2);
    ctx.stroke();
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(0, -radius + 5);
    ctx.moveTo(0, 0);
    ctx.lineTo(-radius + 6, radius * 0.48);
    ctx.moveTo(0, 0);
    ctx.lineTo(radius - 6, radius * 0.48);
    ctx.stroke();
    ctx.fillStyle = angle < -0.08 ? "#38bdf8" : angle > 0.08 ? "#facc15" : "#94a3b8";
    ctx.beginPath();
    ctx.arc(0, 0, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function drawGauge(ctx, cx, cy, radius, ratio, color, label, value) {
    ctx.strokeStyle = "rgba(148,163,184,.5)";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, Math.PI * 0.82, Math.PI * 2.18);
    ctx.stroke();
    ctx.strokeStyle = color;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, Math.PI * 0.82, Math.PI * (0.82 + 1.36 * clamp(ratio, 0, 1)));
    ctx.stroke();
    const needle = Math.PI * (0.82 + 1.36 * clamp(ratio, 0, 1));
    ctx.strokeStyle = "#f8fafc";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(needle) * (radius - 5), cy + Math.sin(needle) * (radius - 5));
    ctx.stroke();
    ctx.fillStyle = "#e5e7eb";
    ctx.font = "700 10px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(label, cx, cy + radius + 10);
    ctx.font = "700 13px system-ui, sans-serif";
    ctx.fillText(value, cx, cy + 5);
    ctx.textAlign = "start";
  }

  function drawRacingDashboard(ctx, state) {
    const y = 414;
    ctx.fillStyle = "rgba(15,23,42,.84)";
    ctx.fillRect(8, y, WIDTH - 16, 58);
    drawGauge(ctx, 48, y + 30, 22, (state.speed || 0) / 235, "#38bdf8", "KM/H", String(Math.round(state.speed || 0)));
    const barX = 88;
    const barW = 112;
    ctx.fillStyle = "rgba(51,65,85,.9)";
    ctx.fillRect(barX, y + 11, barW, 8);
    ctx.fillRect(barX, y + 31, barW, 8);
    ctx.fillStyle = "#22d3ee";
    ctx.fillRect(barX, y + 11, barW * clamp((state.nitro || 0) / 100, 0, 1), 8);
    ctx.fillStyle = state.integrity > 35 ? "#22c55e" : "#fb7185";
    ctx.fillRect(barX, y + 31, barW * clamp((state.integrity || 0) / 100, 0, 1), 8);
    ctx.fillStyle = "#e5e7eb";
    ctx.font = "700 10px system-ui, sans-serif";
    ctx.fillText("氮氣", barX, y + 9);
    ctx.fillText("車況", barX, y + 29);
    const detail = state.item ? pickupDetail(state.item) : null;
    ctx.fillStyle = detail ? detail.color : "rgba(100,116,139,.9)";
    ctx.fillRect(214, y + 12, 34, 34);
    ctx.fillStyle = detail ? "#0f172a" : "#cbd5e1";
    ctx.font = "700 18px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(detail ? detail.label : "-", 231, y + 35);
    ctx.font = "700 9px system-ui, sans-serif";
    ctx.fillStyle = "#e5e7eb";
    ctx.fillText(state.shieldTicks > 0 ? "護盾" : "道具", 231, y + 55);
    ctx.textAlign = "start";
    if (state.itemBoostTicks > 0) {
      ctx.fillStyle = "rgba(250,204,21,.28)";
      ctx.fillRect(252, y + 12, 26, 34);
      ctx.fillStyle = "#facc15";
      ctx.font = "700 10px system-ui, sans-serif";
      ctx.fillText("BOOST", 251, y + 33);
    }
    drawRacingSteeringWheel(ctx, state, 316, y + 31, 22);
  }

  function drawRacingScene(ctx, state) {
    ctx.save();
    if (state.impactShake > 0) {
      const shake = Math.min(7, state.impactShake * 0.28);
      ctx.translate((racingRandom(state) - 0.5) * shake, (racingRandom(state) - 0.5) * shake);
    }
    drawRacingBackdrop(ctx, state);
    (state.pickups || []).slice().sort((a, b) => a.y - b.y).forEach((pickup) => drawRacingPickup(ctx, state, pickup));
    drawRacingOilSlicks(ctx, state);
    drawRacingSkidMarks(ctx, state);
    (state.traffic || []).slice().sort((a, b) => a.y - b.y).forEach((car) => {
      const t = roadT(car.y);
      const wiggle = car.disrupted ? Math.sin((state.tick + car.y) * 0.13) * 0.14 : 0;
      const rotation = clamp(Number(car.laneVelocity || 0) * 0.22 + wiggle * 0.15, -0.26, 0.26);
      drawRacingCar(ctx, trafficScreenX(car, state) + wiggle * 11 * t, car.y, 22 + t * 23, 34 + t * 38, car.disrupted ? "#c084fc" : car.color, "#dbeafe", rotation);
    });
    drawRacingImpactParticles(ctx, state);
    drawRacingCar(ctx, state.playerX + Number(state.drift || 0) * Number(state.lastSteer || 0) * 5, PLAYER_Y, PLAYER_CAR_WIDTH, PLAYER_CAR_HEIGHT, state.shieldTicks > 0 ? "#22c55e" : "#ef4444", "#fef2f2", Number(state.steeringAngle || 0) * 0.18);
    if (state.nitroActive) {
      ctx.fillStyle = "rgba(56,189,248,.42)";
      ctx.beginPath();
      ctx.moveTo(state.playerX - 16, PLAYER_Y + 34);
      ctx.lineTo(state.playerX, PLAYER_Y + 72);
      ctx.lineTo(state.playerX + 16, PLAYER_Y + 34);
      ctx.closePath();
      ctx.fill();
    }
    if (state.drift > 0.1) {
      ctx.strokeStyle = "rgba(250,204,21,.6)";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(state.playerX, PLAYER_Y + 2, 33 + state.drift * 8, 0.3, Math.PI - 0.3);
      ctx.stroke();
    }
    ctx.restore();
    drawRacingHud(ctx, state);
    drawRacingMinimap(ctx, state);
    drawRacingDashboard(ctx, state);
    if (state.countdownTicks > 0 && state.status === "active") {
      const label = state.countdownTicks > 62 ? "3" : state.countdownTicks > 32 ? "2" : state.countdownTicks > 6 ? "1" : "GO";
      ctx.fillStyle = "rgba(15,23,42,.54)";
      ctx.fillRect(0, 0, WIDTH, HEIGHT);
      ctx.fillStyle = label === "GO" ? "#22c55e" : "#facc15";
      ctx.font = `800 ${label === "GO" ? 52 : 68}px system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, WIDTH / 2, HEIGHT / 2 - 12);
      ctx.textAlign = "start";
      ctx.textBaseline = "alphabetic";
    }
  }

  function makeTraffic(state) {
    if ((state.traffic || []).length >= MAX_TRAFFIC_CARS) return;
    const spawnY = HORIZON_Y + 8;
    const lane = chooseTrafficLane(state, spawnY);
    if (lane === null) return;
    const color = CAR_COLORS[Math.floor(racingRandom(state) * CAR_COLORS.length)] || "#38bdf8";
    state.traffic.push({
      lane,
      laneOffset: 0,
      laneVelocity: 0,
      y: spawnY,
      color,
      roadSpeed: 54 + racingRandom(state) * 48,
      mass: 0.8 + racingRandom(state) * 0.55,
      passed: false,
      hit: false,
      collisionCooldown: 0,
      disrupted: state.jammerTicks > 0 ? 90 : 0,
    });
  }

  function makePickup(state) {
    const lane = choosePickupLane(state);
    const roll = racingRandom(state);
    const type = roll < 0.38 ? "nitro" : roll < 0.58 ? "boost" : roll < 0.78 ? "jammer" : roll < 0.91 ? "oil" : "shield";
    state.pickups.push({ lane, y: HORIZON_Y + 8, collected: false, type });
  }

  function collectRacingPickup(api, state, pickup) {
    const type = pickup.type || "nitro";
    state.pickupsCollected += 1;
    if (type === "nitro") {
      state.nitro = Math.min(100, state.nitro + 30);
    } else if (!state.item) {
      state.item = type;
    } else {
      state.nitro = Math.min(100, state.nitro + 16);
    }
    api.sound?.("uiDrop", { volume: 0.12, throttleMs: 120 });
  }

  function disruptRacingTraffic(api, state, label) {
    let affected = 0;
    (state.traffic || []).forEach((car) => {
      if (car.y < PLAYER_Y + 84 && car.y > HORIZON_Y - 8 && Math.abs(car.y - PLAYER_Y) < 250) {
        car.disrupted = Math.max(car.disrupted || 0, label === "oil" ? 150 : 110);
        if (Math.abs(car.lane) < 1 && racingRandom(state) > 0.45) car.lane += racingRandom(state) > 0.5 ? 1 : -1;
        affected += 1;
      }
    });
    if (affected === 0) {
      state.jammerTicks = Math.max(state.jammerTicks || 0, 90);
      affected = 1;
    }
    state.interference += affected;
    state.score += affected * 120;
    api.sound?.("uiSwitch", { volume: 0.12, throttleMs: 220 });
    api.mission?.("interference-3", state.interference, 3, "道具干擾 3 次");
    if (state.interference >= 3) api.achievement?.("interference-hit", "道具干擾", "用道具干擾 3 次以上對手。");
  }

  function useRacingItem(api, state) {
    if (state.status !== "active" || !state.item) return;
    const item = state.item;
    state.item = null;
    state.itemsUsed += 1;
    if (item === "boost") {
      state.itemBoostTicks = Math.max(state.itemBoostTicks || 0, 92);
      state.speed += 34;
      state.nitro = Math.min(100, state.nitro + 10);
      api.sound?.("uiSuccess", { volume: 0.12, throttleMs: 260 });
    } else if (item === "shield") {
      state.shieldTicks = Math.max(state.shieldTicks || 0, 250);
      api.sound?.("uiSelect", { volume: 0.13, throttleMs: 260 });
    } else if (item === "oil") {
      state.oilSlicks.push({ x: state.playerX, y: PLAYER_Y + 43, life: 150 });
      disruptRacingTraffic(api, state, "oil");
    } else {
      disruptRacingTraffic(api, state, "jammer");
    }
    api.mission?.("item-3", state.itemsUsed, 3, "使用道具 3 次");
  }

  function updateRacingDrift(api, state, steer) {
    const drifting = Boolean(state.controls.brake && Math.abs(steer) > 0 && state.speed > 72);
    if (!drifting) {
      state.drift = Math.max(0, Number(state.drift || 0) - 0.08);
      state.currentDrift = 0;
      return;
    }
    state.drift = Math.min(1, Number(state.drift || 0) + 0.09);
    state.currentDrift += 1;
    const gain = 0.8 + Math.min(3.2, state.speed / 95);
    state.driftScore += gain;
    state.nitro = Math.min(100, state.nitro + 0.22);
    if (state.tick % 4 === 0) {
      state.skidMarks.push({ x: state.playerX, y: PLAYER_Y + 34, lean: steer, alpha: 0.58 });
    }
    if (state.driftScore - Number(state.lastDriftMissionScore || 0) >= 24 || (state.driftScore >= 180 && !state.driftMissionCompleteSent)) {
      state.lastDriftMissionScore = state.driftScore;
      state.driftMissionCompleteSent = state.driftScore >= 180;
      api.mission?.("drift-180", state.driftScore, 180, "甩尾 180 分");
    }
    if (state.driftScore >= 180 && !state.driftAchievementSent) {
      state.driftAchievementSent = true;
      api.achievement?.("drift-chain", "甩尾入彎", "單局累積 180 甩尾分。");
    }
  }

  function applyRacingRoadBoundary(api, state) {
    const bounds = roadBoundsAt(PLAYER_Y, state);
    const leftLimit = bounds.left + PLAYER_CAR_WIDTH * 0.28;
    const rightLimit = bounds.right - PLAYER_CAR_WIDTH * 0.28;
    let impacted = false;
    if (state.playerX < leftLimit) {
      state.playerX = leftLimit;
      state.lateralVelocity = Math.max(2.6, Math.abs(Number(state.lateralVelocity || 0)) * 0.55);
      impacted = true;
    } else if (state.playerX > rightLimit) {
      state.playerX = rightLimit;
      state.lateralVelocity = -Math.max(2.6, Math.abs(Number(state.lateralVelocity || 0)) * 0.55);
      impacted = true;
    }
    if (!impacted) return;
    state.speed *= 0.86;
    if (state.edgeImpactCooldown <= 0) {
      state.integrity = Math.max(0, state.integrity - (state.speed > 120 ? 5.5 : 2.2));
      state.edgeImpactCooldown = EDGE_IMPACT_COOLDOWN;
      state.impactShake = Math.max(state.impactShake || 0, 13);
      addRacingImpactParticles(state, state.playerX, PLAYER_Y + 22, "#f97316", 9);
      api.sound?.("metalHit", { volume: 0.14, throttleMs: 240 });
    }
  }

  function trafficLaneOpenNear(state, lane, y, self) {
    return !(state.traffic || []).some((car) => car !== self && Math.abs(Number(car.lane || 0) - lane) < 0.45 && Math.abs(Number(car.y || 0) - y) < TRAFFIC_MIN_SCREEN_GAP);
  }

  function updateRacingTrafficSeparation(state) {
    const cars = (state.traffic || []).slice().sort((a, b) => a.y - b.y);
    for (let i = 0; i < cars.length; i += 1) {
      const car = cars[i];
      car.laneOffset = clamp(Number(car.laneOffset || 0) + Number(car.laneVelocity || 0), -0.36, 0.36);
      car.laneVelocity = Number(car.laneVelocity || 0) * 0.82 - Number(car.laneOffset || 0) * 0.08;
      for (let j = i + 1; j < cars.length; j += 1) {
        const other = cars[j];
        if (Math.abs(Number(car.lane || 0) - Number(other.lane || 0)) > 0.45) continue;
        const gap = Math.abs(Number(other.y || 0) - Number(car.y || 0));
        if (gap >= TRAFFIC_MIN_SCREEN_GAP) continue;
        const alternatives = LANES.filter((lane) => lane !== other.lane && trafficLaneOpenNear(state, lane, other.y, other));
        if (alternatives.length && racingRandom(state) > 0.32) {
          other.lane = alternatives[Math.floor(racingRandom(state) * alternatives.length)];
          other.laneVelocity += (other.lane > car.lane ? 0.035 : -0.035);
        } else {
          other.y = car.y + TRAFFIC_MIN_SCREEN_GAP;
          other.roadSpeed = Math.max(34, Number(other.roadSpeed || 64) - 4);
        }
      }
    }
  }

  function resolveRacingTrafficCollision(api, state, car) {
    if (car.collisionCooldown > 0) return;
    const playerBox = playerCollisionBox(state);
    const carBox = trafficCollisionBox(car, state);
    if (!racingRectsOverlap(playerBox, carBox)) return;

    const carX = trafficScreenX(car, state);
    const side = state.playerX <= carX ? -1 : 1;
    const overlapX = Math.min(playerBox.right - carBox.left, carBox.right - playerBox.left);
    const relativeSpeed = Math.max(18, Math.abs(Number(state.speed || 0) - Number(car.roadSpeed || 70)));
    car.collisionCooldown = 42;
    car.hit = true;
    car.disrupted = Math.max(car.disrupted || 0, state.shieldTicks > 0 ? 140 : 90);
    car.laneOffset = clamp(Number(car.laneOffset || 0) - side * 0.18, -0.34, 0.34);
    car.laneVelocity = clamp(Number(car.laneVelocity || 0) - side * 0.055, -0.12, 0.12);
    state.playerX += side * Math.min(20, Math.max(7, overlapX * 0.58));
    state.lateralVelocity = side * Math.max(3.4, relativeSpeed / 42);
    state.impactShake = Math.max(state.impactShake || 0, state.shieldTicks > 0 ? 12 : 22);
    addRacingImpactParticles(state, (state.playerX + carX) / 2, PLAYER_Y - 8, state.shieldTicks > 0 ? "#22c55e" : "#facc15", state.shieldTicks > 0 ? 12 : 18);

    if (state.shieldTicks > 0) {
      state.shieldTicks = Math.max(0, state.shieldTicks - 90);
      state.interference += 1;
      state.speed *= 0.82;
      api.sound?.("uiSuccess", { volume: 0.13, throttleMs: 220 });
      api.mission?.("interference-3", state.interference, 3, "道具干擾 3 次");
      return;
    }

    const damage = clamp(8 + relativeSpeed * 0.16 + Math.max(0, state.speed - 120) * 0.08, 10, 30);
    state.integrity = Math.max(0, state.integrity - damage);
    state.speed = Math.max(0, state.speed * 0.52 - 8);
    api.sound?.("metalHit", { volume: 0.18, throttleMs: 200 });
  }

  function updateRacingGame(api, state, ctx) {
    if (state.status !== "active") return;
    state.tick += 1;
    if (state.edgeImpactCooldown > 0) state.edgeImpactCooldown -= 1;
    if (state.impactShake > 0) state.impactShake -= 1;
    state.curve += (state.targetCurve - state.curve) * 0.014;
    if (state.tick % 260 === 0) state.targetCurve = (racingRandom(state) - 0.5) * 1.55;

    if (state.countdownTicks > 0) {
      state.countdownTicks -= 1;
      state.speed = 0;
      state.nitroActive = false;
      drawRacingScene(ctx, state);
      api.status("起跑倒數 · 距離尚未開始計算");
      return;
    }

    if (state.itemBoostTicks > 0) {
      state.itemBoostTicks -= 1;
      state.speed += 1.1;
    }
    if (state.shieldTicks > 0) state.shieldTicks -= 1;
    if (state.jammerTicks > 0) state.jammerTicks -= 1;

    const throttle = state.controls.throttle || state.controls.nitro;
    if (throttle) state.speed += 1.85 + Math.max(0, 80 - state.speed) * 0.014;
    else state.speed -= 1.18;
    if (state.controls.brake) state.speed -= 4.2 + Math.min(1.4, state.speed / 170);
    state.nitroActive = Boolean(state.controls.nitro && state.nitro > 0 && state.speed > 38);
    if (state.nitroActive) {
      state.speed += 3.05;
      state.nitro = Math.max(0, state.nitro - 1.48);
      if (!state.nitroHeldLastFrame) {
        state.nitroBursts += 1;
        api.sound?.("uiSwitch", { volume: 0.11, throttleMs: 240 });
        if (state.nitroBursts >= 3) api.achievement?.("nitro-master", "氮氣掌握", "單局使用 3 次以上氮氣。");
        api.mission?.("nitro-3", state.nitroBursts, 3, "氮氣衝刺 3 次");
      }
    } else {
      state.nitro = Math.min(100, state.nitro + 0.08);
    }
    state.nitroHeldLastFrame = state.nitroActive;
    const speedLimit = state.nitroActive ? 235 : (state.itemBoostTicks > 0 ? 225 : 205);
    state.speed = clamp(state.speed, 0, speedLimit);

    const steer = (state.controls.left ? -1 : 0) + (state.controls.right ? 1 : 0);
    state.lastSteer = steer;
    state.steeringAngle += (steer * 0.72 - state.steeringAngle) * 0.18;
    updateRacingDrift(api, state, steer);
    const steerGrip = state.controls.brake ? 0.54 : 1;
    state.lateralVelocity += steer * (0.72 + state.speed / 210) * steerGrip;
    state.lateralVelocity += Number(state.curve || 0) * -0.055 * Math.max(0.7, state.speed / 150);
    state.lateralVelocity *= state.controls.brake ? 0.93 : 0.88;
    state.playerX += state.lateralVelocity + steer * Number(state.drift || 0) * 0.9;
    applyRacingRoadBoundary(api, state);

    if (state.speed > 0.1) state.distance += state.speed * 0.0235;
    state.score = Math.max(0, Math.round(state.distance * 0.26 + state.overtakes * 180 + state.pickupsCollected * 105 + state.checkpoints * 260 + state.maxSpeed * 3 + state.driftScore * 2.1 + state.interference * 145 - (100 - state.integrity) * 12));
    state.maxSpeed = Math.max(state.maxSpeed, state.speed);

    if (state.speed > 32 && state.tick >= state.nextTrafficTick) {
      makeTraffic(state);
      state.nextTrafficTick = state.tick + Math.max(34, 78 - Math.floor(state.speed / 7)) + Math.floor(racingRandom(state) * 34);
    }
    if (state.speed > 22 && state.tick >= state.nextPickupTick) {
      makePickup(state);
      state.nextPickupTick = state.tick + 170 + Math.floor(racingRandom(state) * 110);
    }

    const travel = Math.max(0, state.speed * 0.052);
    state.skidMarks.forEach((mark) => {
      mark.y += travel * 0.96;
      mark.alpha -= 0.005;
    });
    state.skidMarks = state.skidMarks.filter((mark) => mark.alpha > 0.05 && mark.y < HEIGHT + 40);
    state.oilSlicks.forEach((slick) => {
      slick.y += travel * 0.82;
      slick.life -= 1;
    });
    state.oilSlicks = state.oilSlicks.filter((slick) => slick.life > 0 && slick.y < HEIGHT + 40);
    state.impactParticles.forEach((particle) => {
      particle.x += particle.vx;
      particle.y += particle.vy + travel * 0.28;
      particle.vy += 0.18;
      particle.life -= 1;
    });
    state.impactParticles = state.impactParticles.filter((particle) => particle.life > 0);

    state.traffic.forEach((car) => {
      if (car.disrupted > 0) car.disrupted -= 1;
      if (car.collisionCooldown > 0) car.collisionCooldown -= 1;
      const carTravel = Number(car.roadSpeed || 64) * 0.031;
      const disruptionDrag = car.disrupted ? 2.1 : 0;
      car.y += travel - carTravel - disruptionDrag;
      resolveRacingTrafficCollision(api, state, car);
      if (!car.passed && car.y > PLAYER_Y + 54) {
        car.passed = true;
        state.overtakes += 1;
        state.nitro = Math.min(100, state.nitro + 4);
        if (state.overtakes >= 8) api.achievement?.("overtake-chain", "連續超車", "單局完成 8 次以上超車。");
        api.mission?.("overtake-8", state.overtakes, 8, "超車 8 台");
      }
    });
    updateRacingTrafficSeparation(state);
    state.traffic = state.traffic.filter((car) => car.y < HEIGHT + 90 && car.y > HORIZON_Y - 70);

    state.pickups.forEach((pickup) => {
      pickup.y += travel + 0.4;
      const x = laneX(pickup.lane, pickup.y, state);
      if (!pickup.collected && pickup.y > PLAYER_Y - 34 && pickup.y < PLAYER_Y + 44 && Math.abs(x - state.playerX) < 32) {
        pickup.collected = true;
        collectRacingPickup(api, state, pickup);
      }
    });
    state.pickups = state.pickups.filter((pickup) => !pickup.collected && pickup.y < HEIGHT + 60);

    if (state.distance >= state.nextCheckpoint) {
      state.checkpoints += 1;
      state.nextCheckpoint += 1500;
      state.nitro = Math.min(100, state.nitro + 18);
      api.sound?.("uiTick", { volume: 0.1, throttleMs: 250 });
    }

    drawRacingScene(ctx, state);
    api.status(`速度 ${Math.round(state.speed)} · 車況 ${Math.round(state.integrity)}% · 超車 ${state.overtakes} · 道具 ${state.item ? pickupDetail(state.item).name : "無"}`);
    if (state.distance >= state.trackLength) finishRacingGame(api, state, ctx, true);
    else if (state.integrity <= 0) finishRacingGame(api, state, ctx, false);
  }

  function finishRacingGame(api, state, ctx, success) {
    if (state.status === "finished") return;
    state.status = "finished";
    clearInterval(state.timer);
    state.timer = null;
    state.completedAt = Date.now();
    state.score = Math.max(1, Math.round(state.score + (success ? 1000 + state.integrity * 10 : 0)));
    drawRacingScene(ctx, state);
    ctx.fillStyle = "rgba(15,23,42,.78)";
    ctx.fillRect(36, 178, 288, 124);
    ctx.textAlign = "center";
    ctx.fillStyle = success ? "#22c55e" : "#fb7185";
    ctx.font = "700 28px system-ui, sans-serif";
    ctx.fillText(success ? "FINISH" : "CRASH", WIDTH / 2, 222);
    ctx.fillStyle = "#e5e7eb";
    ctx.font = "13px system-ui, sans-serif";
    ctx.fillText(`分數 ${state.score.toLocaleString()} · 超車 ${state.overtakes} · 甩尾 ${Math.round(state.driftScore)}`, WIDTH / 2, 252);
    ctx.textAlign = "start";
    api.sound?.(success ? "uiSuccess" : "uiError", { volume: 0.16, throttleMs: 500 });
    if (success) api.achievement?.("first-finish", "完賽衝線", "完成一場街頭賽車。");
    if (success && state.integrity >= 72) api.achievement?.("clean-racer", "乾淨跑法", "低損傷完賽。");
    registerScore(api, state.score, state, state.dailyChallenge?.difficulty || "standard");
    api.status(`${success ? "完賽" : "失事"} · 分數 ${state.score.toLocaleString()} · 最高速 ${Math.round(state.maxSpeed)}`);
  }

  window.registerHackmeLocalGameModule("racing", {
    mount(api) {
      makeCtx(api, "街頭賽車");
      api.setSwipeMode?.("hold");
      const state = {
        status: "idle",
        timer: null,
        startedAt: 0,
        completedAt: null,
        dailyChallenge: null,
        rng: null,
        controls: { left: false, right: false, throttle: false, brake: false, nitro: false },
        tick: 0,
        countdownTicks: 0,
        speed: 0,
        maxSpeed: 0,
        distance: 0,
        trackLength: 6500,
        nextCheckpoint: 1500,
        checkpoints: 0,
        score: 0,
        integrity: 100,
        nitro: 55,
        nitroActive: false,
        nitroHeldLastFrame: false,
        nitroBursts: 0,
        item: null,
        itemsUsed: 0,
        itemBoostTicks: 0,
        shieldTicks: 0,
        jammerTicks: 0,
        interference: 0,
        drift: 0,
        currentDrift: 0,
        driftScore: 0,
        lastDriftMissionScore: 0,
        driftMissionCompleteSent: false,
        driftAchievementSent: false,
        steeringAngle: 0,
        lastSteer: 0,
        lateralVelocity: 0,
        edgeImpactCooldown: 0,
        impactShake: 0,
        skidMarks: [],
        oilSlicks: [],
        impactParticles: [],
        playerX: WIDTH / 2,
        curve: 0,
        targetCurve: 0,
        traffic: [],
        pickups: [],
        pickupsCollected: 0,
        overtakes: 0,
        nextTrafficTick: START_COUNTDOWN_TICKS + 88,
        nextPickupTick: START_COUNTDOWN_TICKS + 130,
      };
      api.root.innerHTML = `<canvas class="arcade-canvas tall racing-canvas" width="${WIDTH}" height="${HEIGHT}" aria-label="街頭賽車"></canvas>`;
      api.setControls(`
        <button class="btn game-mini-btn" data-hold="left" type="button">左</button>
        <button class="btn game-mini-btn" data-hold="right" type="button">右</button>
        <button class="btn game-mini-btn" data-hold="brake" type="button">煞車</button>
        <button class="btn game-mini-btn btn-primary" data-action="new" type="button">開始</button>
        <button class="btn game-mini-btn" data-action="item" type="button">道具</button>
        <button class="btn game-mini-btn" data-hold="throttle" type="button">加速</button>
        <button class="btn game-mini-btn" data-hold="nitro" type="button">氮氣</button>
      `);
      const canvas = api.root.querySelector("canvas");
      const ctx = canvas.getContext("2d");

      const reset = () => {
        clearInterval(state.timer);
        const dailyChallenge = api.dailyChallenge?.() || null;
        Object.assign(state, {
          status: "active",
          timer: null,
          startedAt: Date.now(),
          completedAt: null,
          dailyChallenge,
          rng: dailyChallenge?.seed ? window.createHackmeGameSeededRandom?.(dailyChallenge.seed) : null,
          tick: 0,
          countdownTicks: START_COUNTDOWN_TICKS,
          speed: 0,
          maxSpeed: 0,
          distance: 0,
          trackLength: dailyChallenge?.modifier === "rush" ? 5600 : 6500,
          nextCheckpoint: 1500,
          checkpoints: 0,
          score: 0,
          integrity: 100,
          nitro: dailyChallenge?.modifier === "combo" ? 85 : 55,
          nitroActive: false,
          nitroHeldLastFrame: false,
          nitroBursts: 0,
          item: null,
          itemsUsed: 0,
          itemBoostTicks: 0,
          shieldTicks: 0,
          jammerTicks: 0,
          interference: 0,
          drift: 0,
          currentDrift: 0,
          driftScore: 0,
          lastDriftMissionScore: 0,
          driftMissionCompleteSent: false,
          driftAchievementSent: false,
          steeringAngle: 0,
          lastSteer: 0,
          lateralVelocity: 0,
          edgeImpactCooldown: 0,
          impactShake: 0,
          skidMarks: [],
          oilSlicks: [],
          impactParticles: [],
          playerX: WIDTH / 2,
          curve: 0,
          targetCurve: 0,
          traffic: [],
          pickups: [],
          pickupsCollected: 0,
          overtakes: 0,
          nextTrafficTick: START_COUNTDOWN_TICKS + 88,
          nextPickupTick: START_COUNTDOWN_TICKS + 130,
        });
        state.controls = { left: false, right: false, throttle: false, brake: false, nitro: false };
        state.timer = setInterval(() => updateRacingGame(api, state, ctx), 16);
        api.sound?.("uiSelect", { volume: 0.13, throttleMs: 300 });
      };

      api.onAction = (action) => {
        if (action === "new") reset();
        if (action === "item") useRacingItem(api, state);
      };
      api.onControl = (target, pressed) => {
        const hold = target.dataset.hold;
        if (hold && Object.prototype.hasOwnProperty.call(state.controls, hold)) state.controls[hold] = pressed;
      };
      api.onKey = (event, pressed) => {
        const key = String(event.key || "").toLowerCase();
        if (["arrowleft", "a"].includes(key)) state.controls.left = pressed;
        if (["arrowright", "d"].includes(key)) state.controls.right = pressed;
        if (["arrowup", "w"].includes(key)) state.controls.throttle = pressed;
        if (["arrowdown", "s"].includes(key)) state.controls.brake = pressed;
        if (key === " ") state.controls.nitro = pressed;
        if (pressed && ["e", "x"].includes(key)) useRacingItem(api, state);
        if (["arrowleft", "arrowright", "arrowup", "arrowdown", " ", "a", "d", "w", "s", "e", "x"].includes(key)) event.preventDefault?.();
      };

      drawRacingScene(ctx, state);
      api.status("待機 · 按開始後加速、超車、甩尾並使用道具。");
      return () => clearInterval(state.timer);
    },
  });
}());
