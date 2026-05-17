'use strict';

(function setupExperimentArea() {
  const PLANE_PARTICLE_COUNT = 160;
  const LIQUID_PARTICLE_COUNT = 240;
  const HUMMINGBIRD_PARTICLE_COUNT = 180;
  const TWO_PI = Math.PI * 2;
  let initialized = false;
  let rafId = 0;
  let lastFrameAt = 0;
  let activeStage = "plane";
  let paused = false;
  const canvasSizeCache = new Map();

  const state = {
    plane: { particles: [] },
    liquid: { particles: [], objects: [], shake: 0, stir: 0, spilled: 0 },
    hummingbird: { particles: [] },
  };

  function $(id) {
    return document.getElementById(id);
  }

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function numberValue(id, fallback) {
    const input = $(id);
    const value = input ? Number(input.value) : NaN;
    return Number.isFinite(value) ? value : fallback;
  }

  function checkedValue(id) {
    const input = $(id);
    return !!(input && input.checked);
  }

  function selectValue(id, fallback, allowed = null) {
    const input = $(id);
    const value = input ? String(input.value || "") : "";
    if (allowed && !allowed.includes(value)) return fallback;
    return value || fallback;
  }

  function randomRange(min, max) {
    return min + Math.random() * (max - min);
  }

  function formatValue(input) {
    if (!input) return "";
    const value = Number(input.value);
    if (!Number.isFinite(value)) return input.value || "";
    const step = Number(input.step || 1);
    return Math.abs(step) < 1 ? value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "") : String(Math.round(value));
  }

  function syncControlValue(input) {
    if (!input || !input.id) return;
    document.querySelectorAll(`[data-experiment-value-for="${input.id}"]`).forEach((node) => {
      node.textContent = formatValue(input);
    });
  }

  function setText(id, text) {
    const node = $(id);
    if (node) node.textContent = text;
  }

  function resizeCanvas(canvas, force = false) {
    if (!canvas) return null;
    const cacheKey = canvas.id || "";
    const cached = cacheKey ? canvasSizeCache.get(cacheKey) : null;
    if (!force && cached && cached.ctx && canvas.width === cached.targetWidth && canvas.height === cached.targetHeight) {
      cached.ctx.setTransform(cached.dpr, 0, 0, cached.dpr, 0, 0);
      return { ctx: cached.ctx, width: cached.width, height: cached.height, dpr: cached.dpr };
    }
    const rect = canvas.getBoundingClientRect();
    const fallbackWidth = canvas.parentElement ? canvas.parentElement.clientWidth : 640;
    const width = Math.max(300, Math.round(rect.width || fallbackWidth || 640));
    const height = Math.max(280, Math.round(rect.height || 420));
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const targetWidth = Math.round(width * dpr);
    const targetHeight = Math.round(height * dpr);
    if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
      canvas.width = targetWidth;
      canvas.height = targetHeight;
    }
    const ctx = cached && cached.ctx ? cached.ctx : canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (cacheKey) {
      canvasSizeCache.set(cacheKey, { width, height, dpr, targetWidth, targetHeight, ctx });
    }
    return { ctx, width, height, dpr };
  }

  function canvasInfo(id) {
    return resizeCanvas($(id), false);
  }

  function resizeCanvases() {
    ["experiment-plane-canvas", "experiment-liquid-canvas", "experiment-hummingbird-canvas"].forEach((id) => resizeCanvas($(id), true));
  }

  function seedPlaneParticles() {
    state.plane.particles = Array.from({ length: PLANE_PARTICLE_COUNT }, () => ({
      x: Math.random(),
      y: randomRange(0.12, 0.88),
      z: Math.random(),
      phase: Math.random() * TWO_PI,
      speed: randomRange(0.55, 1.25),
    }));
  }

  function seedLiquidParticles() {
    const level = numberValue("experiment-liquid-level", 68) / 100;
    const top = 1 - level;
    state.liquid.particles = Array.from({ length: LIQUID_PARTICLE_COUNT }, () => ({
      x: randomRange(0.12, 0.88),
      y: randomRange(top + 0.04, 0.95),
      vx: randomRange(-0.002, 0.002),
      vy: randomRange(-0.001, 0.002),
      r: randomRange(1.4, 2.8),
    }));
    state.liquid.objects = [];
    state.liquid.shake = 0;
    state.liquid.stir = 0;
    state.liquid.spilled = 0;
  }

  function seedHummingbirdParticles() {
    state.hummingbird.particles = Array.from({ length: HUMMINGBIRD_PARTICLE_COUNT }, () => ({
      x: randomRange(-0.38, 0.38),
      y: randomRange(-0.15, 0.95),
      phase: Math.random() * TWO_PI,
      speed: randomRange(0.35, 1.15),
      side: Math.random() < 0.5 ? -1 : 1,
    }));
  }

  function drawArrow(ctx, fromX, fromY, toX, toY, color, label, options = {}) {
    const angle = Math.atan2(toY - fromY, toX - fromX);
    const width = options.width || 3;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(fromX, fromY);
    ctx.lineTo(toX, toY);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(toX, toY);
    ctx.lineTo(toX - Math.cos(angle - 0.55) * 12, toY - Math.sin(angle - 0.55) * 12);
    ctx.lineTo(toX - Math.cos(angle + 0.55) * 12, toY - Math.sin(angle + 0.55) * 12);
    ctx.closePath();
    ctx.fill();
    if (label) {
      const labelX = options.labelX ?? (toX + 8);
      const labelY = options.labelY ?? (toY - 8);
      ctx.font = `${options.fontSize || 12}px system-ui, sans-serif`;
      const metrics = ctx.measureText(label);
      const boxW = metrics.width + 14;
      const boxH = (options.fontSize || 12) + 10;
      ctx.fillStyle = options.labelBg || "rgba(6, 16, 24, 0.72)";
      roundedRect(ctx, labelX - 7, labelY - boxH + 4, boxW, boxH, 7);
      ctx.fill();
      ctx.fillStyle = color;
      ctx.fillText(label, labelX, labelY);
    }
    ctx.restore();
  }

  function roundedRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + width - r, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + r);
    ctx.lineTo(x + width, y + height - r);
    ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
    ctx.lineTo(x + r, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  function drawLabel(ctx, text, x, y, color = "rgba(255, 255, 255, 0.9)") {
    ctx.save();
    ctx.font = "12px system-ui, sans-serif";
    const metrics = ctx.measureText(text);
    ctx.fillStyle = "rgba(5, 13, 20, 0.72)";
    roundedRect(ctx, x - 7, y - 17, metrics.width + 14, 23, 7);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.fillText(text, x, y);
    ctx.restore();
  }

  function drawLegend(ctx, items, x, y) {
    ctx.save();
    ctx.font = "12px system-ui, sans-serif";
    const width = Math.max(...items.map((item) => ctx.measureText(item.label).width)) + 42;
    const height = 18 + items.length * 22;
    ctx.fillStyle = "rgba(5, 13, 20, 0.68)";
    roundedRect(ctx, x, y, width, height, 10);
    ctx.fill();
    items.forEach((item, index) => {
      const rowY = y + 20 + index * 22;
      ctx.fillStyle = item.color;
      ctx.beginPath();
      ctx.arc(x + 16, rowY - 4, 5, 0, TWO_PI);
      ctx.fill();
      ctx.fillStyle = "rgba(255, 255, 255, 0.88)";
      ctx.fillText(item.label, x + 29, rowY);
    });
    ctx.restore();
  }

  function planeMetrics() {
    const aoa = numberValue("experiment-plane-aoa", 7);
    const flap = numberValue("experiment-plane-flap", 8);
    const wind = numberValue("experiment-plane-wind", 35);
    const speed = numberValue("experiment-plane-speed", 72);
    const spoiler = checkedValue("experiment-plane-spoiler");
    const effectiveAoa = aoa + flap * 0.38;
    const relativeWind = Math.max(5, speed + wind * 0.75);
    const aoaLift = clamp(Math.sin((effectiveAoa + 7) * Math.PI / 34), -0.25, 1.25);
    const stall = clamp((effectiveAoa - 13) * 7 + Math.max(0, 55 - speed) * 0.9 + (spoiler ? 8 : 0), 0, 100);
    const stallRatio = stall / 100;
    const postStallLiftFactor = clamp(1 - stallRatio ** 1.35 * 0.72, 0.28, 1);
    const rawLift = (relativeWind / 110) ** 2 * (0.35 + Math.max(0, aoaLift)) * (1 + flap / 80) * (spoiler ? 0.62 : 1) * 78;
    const lift = clamp(rawLift * postStallLiftFactor, 0, 180);
    const drag = clamp((relativeWind / 115) ** 2 * (22 + Math.abs(aoa) * 2.4 + flap * 1.3 + stall * 0.85 + (spoiler ? 36 : 0)), 0, 220);
    return { aoa, flap, wind, speed, spoiler, effectiveAoa, relativeWind, lift, drag, stall };
  }

  function drawPlaneBackdrop(ctx, width, height, viewLabel) {
    ctx.clearRect(0, 0, width, height);
    const sky = ctx.createLinearGradient(0, 0, 0, height);
    sky.addColorStop(0, "#12304d");
    sky.addColorStop(1, "#071217");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.14)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, height * 0.78);
    ctx.quadraticCurveTo(width * 0.5, height * 0.74, width, height * 0.79);
    ctx.stroke();
    if (viewLabel) drawLabel(ctx, viewLabel, width - Math.min(190, width * 0.42), 40, "#e0f2fe");
  }

  function planeViewMode() {
    return selectValue("experiment-plane-view", "side", ["side", "top", "front", "three-quarter"]);
  }

  function planeViewLabel(view) {
    if (view === "top") return "俯視翼面";
    if (view === "front") return "迎風前視";
    if (view === "three-quarter") return "斜上方視角";
    return "側面剖面";
  }

  function resetPlaneParticle(p) {
    p.x = -0.08;
    p.y = randomRange(0.12, 0.88);
    p.z = Math.random();
    p.speed = randomRange(0.55, 1.25);
  }

  function updatePlaneKpis(metrics) {
    setText("experiment-plane-lift", `${Math.round(metrics.lift)}`);
    setText("experiment-plane-drag", `${Math.round(metrics.drag)}`);
    setText("experiment-plane-stall", `${Math.round(metrics.stall)}%`);
  }

  function drawPlaneSideView(ctx, width, height, time, dt, metrics, vortices) {
    const step = Math.min(dt || 16, 40) / 16.67;

    const centerX = width * 0.52;
    const centerY = height * 0.52;
    const wingLength = Math.min(width * 0.44, 360);
    const flowSpeed = 0.0018 * metrics.relativeWind;
    drawLabel(ctx, "迎面氣流", 18, 40, "#7dd3fc");
    for (let i = 0; i < 5; i += 1) {
      const y = 64 + i * 36;
      drawArrow(ctx, 18, y, Math.min(150, width * 0.22), y, "rgba(125, 211, 252, 0.9)", "", { width: 2 });
    }

    state.plane.particles.forEach((p) => {
      p.x += flowSpeed * p.speed * step;
      if (p.x > 1.08) {
        resetPlaneParticle(p);
      }
      const px = p.x * width;
      const wingZone = clamp(1 - Math.abs(px - centerX) / (wingLength * 0.58), 0, 1);
      const deflect = wingZone * (metrics.effectiveAoa / 23) * 34;
      const separatedFlow = metrics.stall > 55 ? (metrics.stall - 55) / 45 : 0;
      const turbulence = (metrics.spoiler ? 1 : 0.25 * separatedFlow) * Math.sin(time * 0.012 + p.phase + p.x * 18) * wingZone * (22 + separatedFlow * 34);
      const tip = vortices ? clamp((px - centerX) / (wingLength * 0.48), -1, 1) : 0;
      const vortex = vortices ? Math.sin(time * 0.018 + p.phase + p.x * 30) * Math.abs(tip) ** 3 * 26 : 0;
      const py = p.y * height + deflect + turbulence + vortex;
      ctx.strokeStyle = `rgba(118, 210, 255, ${0.22 + wingZone * 0.36})`;
      ctx.lineWidth = 1.25;
      ctx.beginPath();
      ctx.moveTo(px - 18, py);
      ctx.lineTo(px + 16, py - deflect * 0.18);
      ctx.stroke();
    });

    ctx.save();
    ctx.translate(centerX, centerY);
    ctx.rotate(-metrics.aoa * Math.PI / 180 * 0.7);
    ctx.fillStyle = "rgba(210, 226, 238, 0.88)";
    ctx.strokeStyle = "rgba(255, 255, 255, 0.72)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.ellipse(wingLength * 0.02, -30, wingLength * 0.18, 22, 0.04, 0, TWO_PI);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "rgba(125, 211, 252, 0.84)";
    ctx.beginPath();
    ctx.ellipse(wingLength * 0.11, -40, 22, 8, 0.03, 0, TWO_PI);
    ctx.fill();
    ctx.fillStyle = "rgba(210, 226, 238, 0.82)";
    ctx.beginPath();
    ctx.moveTo(-wingLength * 0.22, -34);
    ctx.lineTo(-wingLength * 0.38, -60);
    ctx.lineTo(-wingLength * 0.32, -28);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "rgba(238, 245, 255, 0.92)";
    ctx.strokeStyle = "rgba(255, 255, 255, 0.72)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(-wingLength / 2, 0);
    ctx.bezierCurveTo(-wingLength * 0.25, -34, wingLength * 0.28, -30, wingLength / 2, -4);
    ctx.bezierCurveTo(wingLength * 0.24, 18, -wingLength * 0.24, 18, -wingLength / 2, 0);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = metrics.spoiler ? "rgba(255, 120, 96, 0.9)" : "rgba(90, 160, 255, 0.72)";
    ctx.fillRect(wingLength * 0.12, -18 - metrics.flap * 0.18, wingLength * 0.18, 8 + metrics.flap * 0.22);
    ctx.strokeStyle = "rgba(255, 214, 102, 0.86)";
    ctx.setLineDash([6, 5]);
    ctx.beginPath();
    ctx.moveTo(-wingLength * 0.42, 34);
    ctx.lineTo(wingLength * 0.42, 34 - Math.tan(metrics.effectiveAoa * Math.PI / 180) * wingLength * 0.32);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();

    if (metrics.stall > 45) {
      ctx.save();
      ctx.fillStyle = "rgba(251, 146, 60, 0.18)";
      ctx.strokeStyle = "rgba(251, 146, 60, 0.72)";
      ctx.lineWidth = 2;
      for (let i = 0; i < 7; i += 1) {
        const x = centerX + wingLength * 0.16 + i * 18;
        const y = centerY - 66 + Math.sin(time * 0.01 + i) * 10;
        ctx.beginPath();
        ctx.arc(x, y, 16 + (i % 3) * 4, 0, TWO_PI);
        ctx.fill();
        ctx.stroke();
      }
      drawLabel(ctx, "失速亂流區", centerX + wingLength * 0.18, centerY - 92, "#fdba74");
      ctx.restore();
    }
    drawLabel(ctx, "機翼 / 襟翼", centerX - wingLength * 0.2, centerY + 56, "#e0f2fe");
    drawArrow(ctx, centerX, centerY - 22, centerX, centerY - 22 - metrics.lift * 0.75, "#6ee7b7", "升力", { labelX: centerX + 12, labelY: centerY - 44 - metrics.lift * 0.55 });
    drawArrow(ctx, centerX - 18, centerY + 34, centerX - 18 - metrics.drag * 0.65, centerY + 34, "#fda4af", "阻力", { labelX: centerX - 108, labelY: centerY + 26 });
    drawLegend(ctx, [
      { color: "#7dd3fc", label: "藍線：氣流" },
      { color: "#6ee7b7", label: "綠箭頭：升力" },
      { color: "#fda4af", label: "紅箭頭：阻力" },
      { color: "#fdba74", label: "橘色：失速風險" },
    ], 14, Math.max(92, height - 130));
    ctx.fillStyle = "rgba(255, 255, 255, 0.72)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`攻角 ${metrics.aoa.toFixed(0)}° · 相對空速 ${metrics.relativeWind.toFixed(0)}`, 16, height - 18);
  }

  function drawPlaneTopView(ctx, width, height, time, dt, metrics, vortices) {
    const step = Math.min(dt || 16, 40) / 16.67;
    const centerX = width * 0.52;
    const centerY = height * 0.52;
    const span = Math.min(width * 0.64, 520);
    const chord = Math.min(height * 0.18, 96);
    const flowSpeed = 0.0018 * metrics.relativeWind;
    drawLabel(ctx, "俯視：看氣流繞過翼面與翼尖", 18, 40, "#7dd3fc");
    for (let i = 0; i < 5; i += 1) {
      const y = centerY - span * 0.42 + i * span * 0.21;
      drawArrow(ctx, 18, y, Math.min(150, width * 0.22), y, "rgba(125, 211, 252, 0.88)", "", { width: 2 });
    }
    state.plane.particles.forEach((p) => {
      if (!Number.isFinite(p.z)) p.z = Math.random();
      p.x += flowSpeed * p.speed * step;
      if (p.x > 1.08) resetPlaneParticle(p);
      const px = p.x * width;
      const baseY = centerY + (p.y - 0.5) * span * 1.08;
      const spanZone = clamp(1 - Math.abs(baseY - centerY) / (span * 0.54), 0, 1);
      const chordZone = clamp(1 - Math.abs(px - centerX) / (chord * 1.45), 0, 1);
      const side = Math.sign(baseY - centerY || 1);
      const separatedFlow = metrics.stall > 55 ? (metrics.stall - 55) / 45 : 0;
      const tipBias = vortices ? Math.abs(baseY - centerY) / (span * 0.5) : 0;
      const wake = chordZone * spanZone * (metrics.effectiveAoa / 20) * 22;
      const swirl = Math.sin(time * 0.017 + p.phase + p.x * 22) * (8 + separatedFlow * 18) * chordZone * (0.2 + tipBias ** 2);
      const py = baseY + side * wake + swirl;
      ctx.strokeStyle = `rgba(118, 210, 255, ${0.22 + chordZone * 0.36})`;
      ctx.lineWidth = 1.15 + p.z * 0.6;
      ctx.beginPath();
      ctx.moveTo(px - 18, py);
      ctx.lineTo(px + 18, py + side * chordZone * 6);
      ctx.stroke();
    });

    ctx.save();
    ctx.translate(centerX, centerY);
    ctx.fillStyle = "rgba(238, 245, 255, 0.9)";
    ctx.strokeStyle = "rgba(255, 255, 255, 0.72)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(-chord * 0.72, -span * 0.5);
    ctx.lineTo(chord * 0.9, -span * 0.36);
    ctx.lineTo(chord * 0.72, span * 0.36);
    ctx.lineTo(-chord * 0.72, span * 0.5);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "rgba(210, 226, 238, 0.88)";
    ctx.beginPath();
    ctx.ellipse(0, 0, chord * 0.48, span * 0.16, 0, 0, TWO_PI);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "rgba(125, 211, 252, 0.86)";
    ctx.beginPath();
    ctx.ellipse(chord * 0.24, 0, chord * 0.24, span * 0.055, 0, 0, TWO_PI);
    ctx.fill();
    ctx.fillStyle = metrics.spoiler ? "rgba(255, 120, 96, 0.9)" : "rgba(90, 160, 255, 0.72)";
    ctx.fillRect(chord * 0.34, -span * 0.28, Math.max(10, chord * 0.14), span * 0.56);
    ctx.fillStyle = "rgba(210, 226, 238, 0.84)";
    ctx.beginPath();
    ctx.moveTo(-chord * 1.6, -span * 0.16);
    ctx.lineTo(-chord * 0.72, -span * 0.08);
    ctx.lineTo(-chord * 0.72, span * 0.08);
    ctx.lineTo(-chord * 1.6, span * 0.16);
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    if (vortices) {
      [-1, 1].forEach((side) => {
        const tipY = centerY + side * span * 0.5;
        ctx.strokeStyle = "rgba(251, 191, 36, 0.75)";
        ctx.lineWidth = 2;
        for (let i = 0; i < 4; i += 1) {
          ctx.beginPath();
          ctx.arc(centerX + chord * 1.0 + i * 20, tipY + Math.sin(time * 0.01 + i) * 5, 11 + i * 3, 0, TWO_PI);
          ctx.stroke();
        }
      });
      drawLabel(ctx, "翼尖渦流", centerX + chord * 1.25, centerY - span * 0.52, "#fdba74");
    }
    drawArrow(ctx, centerX - chord * 0.1, centerY, centerX - chord * 1.4, centerY, "#fda4af", "阻力", { labelX: centerX - chord * 1.7, labelY: centerY - 10 });
    ctx.strokeStyle = "#6ee7b7";
    ctx.lineWidth = 2;
    for (let r = 12; r <= 34; r += 11) {
      ctx.beginPath();
      ctx.arc(centerX, centerY, r, 0, TWO_PI);
      ctx.stroke();
    }
    drawLabel(ctx, "升力朝畫面外", centerX + 42, centerY + 8, "#6ee7b7");
    drawLegend(ctx, [
      { color: "#7dd3fc", label: "藍線：平面氣流" },
      { color: "#fdba74", label: "黃圈：翼尖渦流" },
      { color: "#6ee7b7", label: "綠圈：升力出畫面" },
    ], 14, Math.max(92, height - 108));
    ctx.fillStyle = "rgba(255, 255, 255, 0.72)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`俯視翼面 · 攻角 ${metrics.aoa.toFixed(0)}° · 相對空速 ${metrics.relativeWind.toFixed(0)}`, 16, height - 18);
  }

  function drawPlaneFrontView(ctx, width, height, time, dt, metrics, vortices) {
    const step = Math.min(dt || 16, 40) / 16.67;
    const centerX = width * 0.5;
    const centerY = height * 0.42;
    const span = Math.min(width * 0.72, 560);
    const flowSpeed = 0.0016 * metrics.relativeWind;
    drawLabel(ctx, "迎風前視：看下洗與左右翼尖", 18, 40, "#7dd3fc");
    state.plane.particles.forEach((p) => {
      if (!Number.isFinite(p.z)) p.z = Math.random();
      p.x += flowSpeed * p.speed * step;
      if (p.x > 1.08) resetPlaneParticle(p);
      const across = (p.y - 0.5) * span * 1.12;
      const wingZone = clamp(1 - Math.abs(across) / (span * 0.55), 0, 1);
      const depth = p.x;
      const downwash = wingZone * (metrics.effectiveAoa / 20) * 58 * depth;
      const separatedFlow = metrics.stall > 55 ? (metrics.stall - 55) / 45 : 0;
      const swirl = Math.sin(time * 0.019 + p.phase + p.y * 19) * separatedFlow * 22 * wingZone;
      const px = centerX + across + swirl;
      const py = centerY - 88 + depth * height * 0.74 + downwash;
      const alpha = 0.18 + depth * 0.48;
      ctx.fillStyle = `rgba(118, 210, 255, ${alpha})`;
      ctx.beginPath();
      ctx.arc(px, py, 1.8 + depth * 2.6, 0, TWO_PI);
      ctx.fill();
      ctx.strokeStyle = `rgba(118, 210, 255, ${alpha * 0.72})`;
      ctx.beginPath();
      ctx.moveTo(px, py - 9);
      ctx.lineTo(px + Math.sin(p.phase + time * 0.01) * 4, py + 12);
      ctx.stroke();
    });

    ctx.save();
    ctx.translate(centerX, centerY);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.74)";
    ctx.fillStyle = "rgba(238, 245, 255, 0.92)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(-span / 2, metrics.aoa * 0.55);
    ctx.quadraticCurveTo(0, -20 - metrics.flap * 0.14, span / 2, metrics.aoa * 0.55);
    ctx.lineTo(span / 2 - 22, 18 + metrics.flap * 0.24);
    ctx.quadraticCurveTo(0, 34, -span / 2 + 22, 18 + metrics.flap * 0.24);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "rgba(210, 226, 238, 0.9)";
    ctx.beginPath();
    ctx.ellipse(0, 4, 38, 52, 0, 0, TWO_PI);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "rgba(125, 211, 252, 0.84)";
    ctx.beginPath();
    ctx.ellipse(0, -12, 24, 12, 0, 0, TWO_PI);
    ctx.fill();
    if (metrics.spoiler) {
      ctx.fillStyle = "rgba(255, 120, 96, 0.9)";
      ctx.fillRect(-span * 0.22, -26, span * 0.44, 8 + metrics.flap * 0.18);
    }
    ctx.restore();

    for (let i = -2; i <= 2; i += 1) {
      const x = centerX + i * span * 0.14;
      drawArrow(ctx, x, centerY + 58, x, centerY + 104 + metrics.effectiveAoa * 1.4, "rgba(125, 211, 252, 0.78)", "", { width: 2 });
    }
    drawLabel(ctx, "下洗氣流", centerX + span * 0.17, centerY + 118, "#7dd3fc");
    if (vortices) {
      [-1, 1].forEach((side) => {
        const tipX = centerX + side * span * 0.5;
        ctx.strokeStyle = "rgba(251, 191, 36, 0.76)";
        ctx.lineWidth = 2;
        for (let i = 0; i < 4; i += 1) {
          ctx.beginPath();
          ctx.arc(tipX + side * i * 10, centerY + 18 + i * 18, 12 + i * 5, 0, TWO_PI);
          ctx.stroke();
        }
      });
    }
    drawArrow(ctx, centerX, centerY - 36, centerX, centerY - 36 - metrics.lift * 0.62, "#6ee7b7", "升力", { labelX: centerX + 12, labelY: centerY - 58 - metrics.lift * 0.45 });
    drawLabel(ctx, "阻力朝畫面內", centerX - 52, centerY + 28, "#fda4af");
    drawLegend(ctx, [
      { color: "#7dd3fc", label: "藍點：迎面氣流" },
      { color: "#fdba74", label: "黃圈：翼尖渦流" },
      { color: "#6ee7b7", label: "綠箭頭：升力" },
    ], 14, Math.max(92, height - 108));
    ctx.fillStyle = "rgba(255, 255, 255, 0.72)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`迎風前視 · 下洗隨攻角與襟翼增加`, 16, height - 18);
  }

  function drawPlaneThreeQuarterView(ctx, width, height, time, dt, metrics, vortices) {
    const step = Math.min(dt || 16, 40) / 16.67;
    const centerX = width * 0.54;
    const centerY = height * 0.5;
    const size = Math.min(width * 0.42, 360);
    const flowSpeed = 0.0018 * metrics.relativeWind;
    const project = (x, y, z) => ({
      x: centerX + x + z * 0.42,
      y: centerY + y - z * 0.24,
    });
    drawLabel(ctx, "斜上方：同時看翼面、下洗與尾流", 18, 40, "#7dd3fc");
    state.plane.particles.forEach((p) => {
      if (!Number.isFinite(p.z)) p.z = Math.random();
      p.x += flowSpeed * p.speed * step;
      if (p.x > 1.08) resetPlaneParticle(p);
      const x = (p.x - 0.5) * width * 1.05;
      const y = (p.y - 0.5) * height * 0.6;
      const z = (p.z - 0.5) * size * 0.75;
      const wingZone = clamp(1 - Math.abs(x) / (size * 0.85), 0, 1) * clamp(1 - Math.abs(y) / (height * 0.32), 0, 1);
      const downwash = wingZone * (metrics.effectiveAoa / 20) * 42;
      const swirl = Math.sin(time * 0.018 + p.phase + p.x * 18) * wingZone * (8 + metrics.stall * 0.18);
      const a = project(x, y + downwash + swirl, z);
      const b = project(x + 34, y + downwash * 1.08, z);
      ctx.strokeStyle = `rgba(118, 210, 255, ${0.18 + wingZone * 0.42 + p.z * 0.18})`;
      ctx.lineWidth = 1.1 + p.z * 0.7;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    });

    const nose = project(size * 0.52, -18, 0);
    const tail = project(-size * 0.55, 18, 0);
    const leftTip = project(-size * 0.18, 28, -size * 0.72);
    const rightTip = project(size * 0.22, -26, size * 0.72);
    ctx.save();
    ctx.fillStyle = "rgba(238, 245, 255, 0.88)";
    ctx.strokeStyle = "rgba(255, 255, 255, 0.72)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(leftTip.x, leftTip.y);
    ctx.quadraticCurveTo(centerX, centerY - 28 - metrics.aoa * 0.55, rightTip.x, rightTip.y);
    ctx.quadraticCurveTo(centerX + 28, centerY + 20 + metrics.flap * 0.2, leftTip.x, leftTip.y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(tail.x, tail.y);
    ctx.quadraticCurveTo(centerX, centerY - 34, nose.x, nose.y);
    ctx.quadraticCurveTo(centerX, centerY + 32, tail.x, tail.y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "rgba(125, 211, 252, 0.84)";
    ctx.beginPath();
    ctx.ellipse(centerX + size * 0.18, centerY - 18, 28, 10, -0.18, 0, TWO_PI);
    ctx.fill();
    ctx.fillStyle = metrics.spoiler ? "rgba(255, 120, 96, 0.9)" : "rgba(90, 160, 255, 0.72)";
    ctx.fillRect(centerX + size * 0.08, centerY - 36 - metrics.flap * 0.16, size * 0.22, 8 + metrics.flap * 0.22);
    ctx.restore();

    if (vortices) {
      [leftTip, rightTip].forEach((tip, idx) => {
        ctx.strokeStyle = "rgba(251, 191, 36, 0.72)";
        ctx.lineWidth = 2;
        for (let i = 0; i < 4; i += 1) {
          ctx.beginPath();
          ctx.arc(tip.x + (idx ? 1 : -1) * i * 16, tip.y + i * 12, 12 + i * 4, 0, TWO_PI);
          ctx.stroke();
        }
      });
      drawLabel(ctx, "翼尖尾渦", rightTip.x - 10, rightTip.y - 18, "#fdba74");
    }
    drawArrow(ctx, centerX, centerY - 18, centerX, centerY - 18 - metrics.lift * 0.68, "#6ee7b7", "升力", { labelX: centerX + 12, labelY: centerY - 42 - metrics.lift * 0.5 });
    drawArrow(ctx, centerX - 10, centerY + 34, centerX - 10 - metrics.drag * 0.55, centerY + 58, "#fda4af", "阻力", { labelX: centerX - 108, labelY: centerY + 52 });
    drawLegend(ctx, [
      { color: "#7dd3fc", label: "藍線：立體感流線" },
      { color: "#fdba74", label: "黃圈：翼尖尾渦" },
      { color: "#6ee7b7", label: "綠箭頭：升力" },
    ], 14, Math.max(92, height - 108));
    ctx.fillStyle = "rgba(255, 255, 255, 0.72)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`斜上方視角 · 相對空速 ${metrics.relativeWind.toFixed(0)}`, 16, height - 18);
  }

  function drawPlane(time, dt) {
    const info = canvasInfo("experiment-plane-canvas");
    if (!info) return;
    const { ctx, width, height } = info;
    const metrics = planeMetrics();
    const vortices = checkedValue("experiment-plane-vortices");
    const view = planeViewMode();
    drawPlaneBackdrop(ctx, width, height, planeViewLabel(view));
    if (view === "top") drawPlaneTopView(ctx, width, height, time, dt, metrics, vortices);
    else if (view === "front") drawPlaneFrontView(ctx, width, height, time, dt, metrics, vortices);
    else if (view === "three-quarter") drawPlaneThreeQuarterView(ctx, width, height, time, dt, metrics, vortices);
    else drawPlaneSideView(ctx, width, height, time, dt, metrics, vortices);
    updatePlaneKpis(metrics);
  }

  function updateLiquid(time, dt) {
    const tilt = numberValue("experiment-liquid-tilt", 0);
    const viscosity = numberValue("experiment-liquid-viscosity", 0.45);
    const level = numberValue("experiment-liquid-level", 68) / 100;
    const top = 1 - level;
    const step = Math.min(dt || 16, 40) / 16.67;
    const tiltForce = Math.sin(tilt * Math.PI / 180) * 0.0032;
    state.liquid.shake = Math.max(0, state.liquid.shake - 0.03 * step);
    state.liquid.stir = Math.max(0, state.liquid.stir - 0.008 * step);
    const stirCenterY = top + level * 0.52;
    const stirStrength = state.liquid.stir * clamp(1.16 - viscosity * 0.45, 0.48, 1.12);
    const fluidTop = top + 0.02;
    const fluidBottom = 0.96;
    const fluidHeight = Math.max(0.12, fluidBottom - fluidTop);
    const thermalScale = clamp(0.0019 - viscosity * 0.0009 + state.liquid.shake * 0.001 + state.liquid.stir * 0.0012, 0.00045, 0.0032);
    let energy = 0;

    state.liquid.particles.forEach((p, index) => {
      const shakeForce = state.liquid.shake * Math.sin(index * 1.7 + time * 0.025) * 0.004;
      const dx = p.x - 0.5;
      const dy = p.y - stirCenterY;
      const distance = Math.sqrt(dx * dx + dy * dy);
      const swirl = clamp(1 - distance / 0.42, 0, 1) * stirStrength;
      const phase = time * 0.003 + index * 12.989;
      const verticalMix = (0.5 - (p.y - fluidTop) / fluidHeight) * 0.00028;
      p.vx += (tiltForce + shakeForce) * step;
      p.vx += (-dy * swirl * 0.010 - dx * swirl * 0.0012) * step;
      p.vy += (dx * swirl * 0.006 - dy * swirl * 0.0008) * step;
      p.vx += Math.sin(phase) * thermalScale * step;
      p.vy += (Math.cos(phase * 1.37) * thermalScale * 0.75 + verticalMix) * step;
      const damping = clamp(0.995 - viscosity * 0.045, 0.88, 0.99);
      p.vx *= damping;
      p.vy *= damping;
      p.x += p.vx * step;
      p.y += p.vy * step;
      if (p.x < 0.06) {
        p.x = 0.06;
        p.vx = Math.abs(p.vx) * 0.48;
      }
      if (p.x > 0.94) {
        p.x = 0.94;
        p.vx = -Math.abs(p.vx) * 0.48;
      }
      if (p.y < fluidTop) {
        p.y = fluidTop;
        p.vy = Math.abs(p.vy) * 0.32;
      }
      if (p.y > fluidBottom) {
        p.y = fluidBottom;
        p.vy = -Math.abs(p.vy) * 0.42;
      }
      energy += p.vx * p.vx + p.vy * p.vy;
    });

    if (Math.abs(tilt) > 42 && state.liquid.particles.length > 60) {
      const spillSide = tilt > 0 ? 1 : -1;
      let removed = 0;
      state.liquid.particles = state.liquid.particles.filter((p) => {
        if (removed >= 2) return true;
        const nearLowerRim = spillSide > 0 ? p.x > 0.86 : p.x < 0.14;
        const nearSurface = p.y < top + 0.26;
        if (nearLowerRim && nearSurface && Math.random() < 0.45) {
          removed += 1;
          return false;
        }
        return true;
      });
      state.liquid.spilled += removed;
      if (removed > 0) {
        state.liquid.objects.forEach((obj) => {
          obj.vx += spillSide * 0.006 * removed;
        });
      }
    }

    state.liquid.objects.forEach((obj) => {
      const dx = obj.x - 0.5;
      const dy = obj.y - stirCenterY;
      const swirl = clamp(1 - Math.sqrt(dx * dx + dy * dy) / 0.46, 0, 1) * stirStrength;
      obj.vy += 0.0015 * step;
      obj.vx += tiltForce * 0.7 * step;
      obj.vx += -dy * swirl * 0.006 * step;
      obj.vy += dx * swirl * 0.0035 * step;
      obj.vx *= 0.985;
      obj.vy *= 0.985;
      obj.x = clamp(obj.x + obj.vx * step, 0.1, 0.9);
      obj.y = clamp(obj.y + obj.vy * step, top + 0.04, 0.93);
    });

    const kinetic = Math.sqrt(energy / Math.max(1, state.liquid.particles.length)) * 1000;
    setText("experiment-liquid-energy", kinetic.toFixed(1));
    setText("experiment-liquid-count", String(state.liquid.particles.length));
    setText("experiment-liquid-objects", String(state.liquid.objects.length));
  }

  function drawLiquid(time, dt) {
    updateLiquid(time, dt);
    const info = canvasInfo("experiment-liquid-canvas");
    if (!info) return;
    const { ctx, width, height, dpr } = info;
    const tilt = numberValue("experiment-liquid-tilt", 0);
    const level = numberValue("experiment-liquid-level", 68) / 100;
    const top = 1 - level;
    ctx.clearRect(0, 0, width, height);
    const bg = ctx.createLinearGradient(0, 0, 0, height);
    bg.addColorStop(0, "#0d2334");
    bg.addColorStop(0.72, "#08141d");
    bg.addColorStop(1, "#0b1114");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = "rgba(255, 255, 255, 0.08)";
    ctx.fillRect(0, height * 0.78, width, height * 0.22);

    const cupWidth = Math.min(width * 0.54, 360);
    const cupHeight = Math.min(height * 0.72, 320);
    const centerX = width * 0.5;
    const centerY = height * 0.52;
    const cupX = -cupWidth / 2;
    const cupY = -cupHeight / 2;
    ctx.save();
    ctx.translate(centerX, centerY);
    ctx.rotate(tilt * Math.PI / 180 * 0.55);

    const cupPath = new Path2D();
    cupPath.moveTo(cupX - 20, cupY);
    cupPath.lineTo(cupX + cupWidth + 20, cupY);
    cupPath.lineTo(cupX + cupWidth - 18, cupY + cupHeight);
    cupPath.lineTo(cupX + 18, cupY + cupHeight);
    cupPath.closePath();

    ctx.save();
    ctx.clip(cupPath);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const waterTopY = centerY + (top - 0.5) * cupHeight;
    const waterBottomY = centerY + cupHeight * 0.6;
    const waterGradient = ctx.createLinearGradient(0, waterTopY, 0, waterBottomY);
    waterGradient.addColorStop(0, "rgba(92, 225, 255, 0.28)");
    waterGradient.addColorStop(1, "rgba(38, 140, 255, 0.2)");
    ctx.fillStyle = waterGradient;
    ctx.fillRect(centerX - cupWidth * 0.72, waterTopY, cupWidth * 1.44, cupHeight * 1.1);
    ctx.strokeStyle = "rgba(180, 245, 255, 0.92)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    const waveLeft = centerX - cupWidth * 0.66;
    const waveRight = centerX + cupWidth * 0.66;
    for (let i = 0; i <= 34; i += 1) {
      const x = waveLeft + (waveRight - waveLeft) * (i / 34);
      const y = waterTopY + Math.sin(time * 0.009 + i * 0.65) * (3 + state.liquid.shake * 7 + state.liquid.stir * 5);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    state.liquid.particles.forEach((p) => {
      const px = centerX + (p.x - 0.5) * cupWidth;
      const py = centerY + (p.y - 0.5) * cupHeight;
      ctx.strokeStyle = "rgba(183, 245, 255, 0.22)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(px - p.vx * 2400, py - p.vy * 2400);
      ctx.lineTo(px, py);
      ctx.stroke();
      ctx.fillStyle = "rgba(120, 225, 255, 0.82)";
      ctx.beginPath();
      ctx.arc(px, py, p.r + 0.4, 0, TWO_PI);
      ctx.fill();
    });
    state.liquid.objects.forEach((obj) => {
      const px = centerX + (obj.x - 0.5) * cupWidth;
      const py = centerY + (obj.y - 0.5) * cupHeight;
      ctx.fillStyle = "rgba(255, 214, 102, 0.88)";
      roundedRect(ctx, px - obj.size / 2, py - obj.size / 2, obj.size, obj.size, 4);
      ctx.fill();
      ctx.strokeStyle = "rgba(255, 255, 255, 0.45)";
      ctx.stroke();
    });
    if (state.liquid.stir > 0.02) {
      const stirVisual = state.liquid.stir;
      const rodX = centerX + Math.sin(time * 0.008) * cupWidth * 0.08;
      const rodTopY = waterTopY - cupHeight * 0.32;
      const rodBottomY = waterTopY + cupHeight * 0.46;
      const rodTilt = Math.sin(time * 0.006) * cupWidth * 0.08;
      ctx.save();
      ctx.strokeStyle = "rgba(219, 242, 255, 0.58)";
      ctx.lineWidth = 9;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(rodX - rodTilt, rodTopY);
      ctx.lineTo(rodX + rodTilt, rodBottomY);
      ctx.stroke();
      ctx.strokeStyle = "rgba(255, 255, 255, 0.82)";
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.moveTo(rodX - rodTilt - 2, rodTopY + 8);
      ctx.lineTo(rodX + rodTilt - 2, rodBottomY - 8);
      ctx.stroke();
      ctx.strokeStyle = `rgba(186, 230, 253, ${0.25 + stirVisual * 0.35})`;
      ctx.lineWidth = 2;
      for (let i = 0; i < 4; i += 1) {
        const radius = 24 + i * 18 + Math.sin(time * 0.01 + i) * 3;
        ctx.beginPath();
        ctx.ellipse(rodX, waterTopY + cupHeight * 0.24, radius, radius * 0.32, Math.sin(time * 0.006) * 0.25, time * 0.006 + i, time * 0.006 + i + Math.PI * 1.35);
        ctx.stroke();
      }
      ctx.restore();
    }
    ctx.restore();

    ctx.strokeStyle = "rgba(255, 255, 255, 0.78)";
    ctx.lineWidth = 3;
    ctx.stroke(cupPath);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.28)";
    ctx.lineWidth = 1;
    for (let i = 1; i <= 5; i += 1) {
      const y = cupY + cupHeight * (i / 6);
      ctx.beginPath();
      ctx.moveTo(cupX + 18, y);
      ctx.lineTo(cupX + 38, y);
      ctx.stroke();
    }
    ctx.fillStyle = "rgba(255, 255, 255, 0.78)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText("杯壁", cupX - 4, cupY + cupHeight + 20);
    ctx.restore();

    drawLabel(ctx, "水平液面", centerX - cupWidth * 0.32, centerY + (top - 0.5) * cupHeight - 12, "#bae6fd");
    drawArrow(ctx, width - 64, 54, width - 64, 128, "#fbbf24", "重力", { labelX: width - 116, labelY: 92, width: 2 });
    if (Math.abs(tilt) > 35 || state.liquid.spilled > 0) {
      const side = tilt >= 0 ? 1 : -1;
      const spillX = centerX + side * cupWidth * 0.42;
      const spillY = centerY - cupHeight * 0.28;
      ctx.save();
      ctx.strokeStyle = "rgba(96, 205, 255, 0.8)";
      ctx.lineWidth = 3;
      for (let i = 0; i < 7; i += 1) {
        const x = spillX + side * (i * 12 + Math.sin(time * 0.012 + i) * 4);
        const y = spillY + i * 20;
        ctx.beginPath();
        ctx.arc(x, y, 2.8, 0, TWO_PI);
        ctx.stroke();
      }
      ctx.restore();
      drawLabel(ctx, "傾角過大：液體倒出", spillX + side * 18, spillY + 8, "#93c5fd");
    }
    drawLegend(ctx, [
      { color: "#78e1ff", label: "藍點：懸浮液體分子" },
      { color: "#ffd666", label: "黃色：丟入物品" },
      { color: "#dbeafe", label: "半透明：玻璃棒" },
      { color: "#fbbf24", label: "箭頭：重力方向" },
    ], 14, 16);
    ctx.fillStyle = "rgba(255, 255, 255, 0.68)";
    ctx.font = "12px system-ui, sans-serif";
    const stirLabel = state.liquid.stir > 0.04 ? " · 玻璃棒攪拌中" : "";
    ctx.fillText(`杯子傾角 ${tilt.toFixed(0)}° · 可見粒子 ${state.liquid.particles.length} · 已倒出 ${state.liquid.spilled}${stirLabel}`, 16, height - 18);
  }

  function hummingbirdMetrics(time) {
    const frequency = numberValue("experiment-hummingbird-frequency", 52);
    const amplitude = numberValue("experiment-hummingbird-amplitude", 58);
    const stability = numberValue("experiment-hummingbird-stability", 72);
    const visualHz = 1.2 + (frequency - 18) / (80 - 18) * 2.4;
    const phase = (time / 1000 * visualHz) % 1;
    const trueCycleMs = 1000 / Math.max(1, frequency);
    const downwash = clamp(frequency * amplitude / (80 * 85) * 120, 0, 120);
    const wobble = Math.abs(Math.sin(phase * TWO_PI)) * (100 - stability) * 0.18;
    const balance = clamp(100 - (100 - stability) * 0.45 - wobble, 0, 100);
    return { frequency, amplitude, stability, phase, visualHz, trueCycleMs, downwash, balance };
  }

  function drawHummingbird(time, dt) {
    const info = canvasInfo("experiment-hummingbird-canvas");
    if (!info) return;
    const { ctx, width, height } = info;
    const metrics = hummingbirdMetrics(time);
    const showBrain = checkedValue("experiment-hummingbird-brain");
    const step = Math.min(dt || 16, 40) / 16.67;
    ctx.clearRect(0, 0, width, height);

    const bg = ctx.createLinearGradient(0, 0, 0, height);
    bg.addColorStop(0, "#10263b");
    bg.addColorStop(1, "#081113");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = "rgba(255, 255, 255, 0.08)";
    for (let i = 0; i < 18; i += 1) {
      ctx.beginPath();
      ctx.arc((i * 97) % width, 28 + ((i * 43) % Math.max(80, height * 0.42)), 1.2, 0, TWO_PI);
      ctx.fill();
    }

    const centerX = width * 0.47;
    const centerY = height * 0.42 + Math.sin(time * 0.003) * (100 - metrics.stability) * 0.035;
    state.hummingbird.particles.forEach((p) => {
      p.y += (0.003 + metrics.downwash * 0.00012) * p.speed * step;
      p.x += Math.sin(time * 0.006 + p.phase) * 0.0009 * p.side * step;
      if (p.y > 1.05) {
        p.y = randomRange(-0.2, 0.1);
        p.x = randomRange(-0.36, 0.36);
      }
      const swirl = Math.sin(time * 0.018 + p.phase + p.y * 8) * 22 * (1 - Math.min(1, Math.abs(p.x)));
      const px = centerX + p.x * width * 0.5 + swirl * 0.15;
      const py = centerY + p.y * height * 0.62;
      ctx.strokeStyle = `rgba(108, 231, 183, ${0.18 + metrics.downwash / 420})`;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(px, py - 20);
      ctx.lineTo(px + swirl * 0.08, py + 14 + metrics.downwash * 0.12);
      ctx.stroke();
    });
    for (let i = 0; i < 4; i += 1) {
      const x = centerX - 74 + i * 48;
      drawArrow(ctx, x, centerY + 54, x + Math.sin(time * 0.006 + i) * 8, centerY + 122 + metrics.downwash * 0.18, "rgba(108, 231, 183, 0.82)", "", { width: 2 });
    }
    drawLabel(ctx, "下洗氣流：翅膀把空氣往下推", centerX - 122, centerY + 150, "#a7f3d0");

    ctx.save();
    ctx.translate(width * 0.75, height * 0.42);
    ctx.strokeStyle = "rgba(76, 175, 96, 0.78)";
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(0, 30);
    ctx.lineTo(0, height * 0.26);
    ctx.stroke();
    ctx.fillStyle = "rgba(72, 187, 120, 0.72)";
    ctx.beginPath();
    ctx.ellipse(-16, 78, 24, 9, -0.6, 0, TWO_PI);
    ctx.fill();
    ctx.fillStyle = "rgba(255, 98, 146, 0.9)";
    for (let i = 0; i < 6; i += 1) {
      ctx.save();
      ctx.rotate(i * TWO_PI / 6);
      ctx.beginPath();
      ctx.ellipse(0, -22, 10, 22, 0, 0, TWO_PI);
      ctx.fill();
      ctx.restore();
    }
    ctx.fillStyle = "#ffd166";
    ctx.beginPath();
    ctx.arc(0, 0, 10, 0, TWO_PI);
    ctx.fill();
    ctx.restore();
    drawLabel(ctx, "花朵目標", width * 0.75 - 28, height * 0.42 - 46, "#fecdd3");
    ctx.save();
    ctx.strokeStyle = "rgba(253, 186, 116, 0.75)";
    ctx.setLineDash([5, 6]);
    ctx.beginPath();
    ctx.moveTo(centerX + 54, centerY - 38);
    ctx.lineTo(width * 0.75 - 18, height * 0.42 - 8);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();

    const wingSwing = Math.sin(metrics.phase * TWO_PI) * metrics.amplitude;
    const asymmetry = (100 - metrics.stability) * 0.18 * Math.sin(time * 0.004);
    ctx.save();
    ctx.translate(centerX, centerY);
    ctx.shadowColor = "rgba(0, 0, 0, 0.28)";
    ctx.shadowBlur = 12;
    ctx.fillStyle = "rgba(67, 160, 118, 0.96)";
    ctx.beginPath();
    ctx.ellipse(0, 2, 20, 36, -0.2, 0, TWO_PI);
    ctx.fill();
    ctx.fillStyle = "rgba(236, 253, 245, 0.9)";
    ctx.beginPath();
    ctx.ellipse(8, 8, 8, 22, -0.12, 0, TWO_PI);
    ctx.fill();
    ctx.fillStyle = "rgba(16, 185, 129, 0.95)";
    ctx.beginPath();
    ctx.arc(4, -30, 14, 0, TWO_PI);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "rgba(255, 255, 255, 0.92)";
    ctx.beginPath();
    ctx.arc(10, -34, 3.4, 0, TWO_PI);
    ctx.fill();
    ctx.fillStyle = "rgba(10, 20, 26, 0.95)";
    ctx.beginPath();
    ctx.arc(11, -34, 1.7, 0, TWO_PI);
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.92)";
    ctx.lineWidth = 5;
    drawWing(ctx, -8, -10, -1, wingSwing - asymmetry, metrics.amplitude);
    drawWing(ctx, 8, -10, 1, -wingSwing - asymmetry, metrics.amplitude);
    ctx.strokeStyle = "rgba(255, 214, 102, 0.94)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(14, -30);
    ctx.lineTo(62, -38);
    ctx.stroke();
    ctx.fillStyle = "rgba(34, 197, 94, 0.82)";
    ctx.beginPath();
    ctx.moveTo(-10, 35);
    ctx.lineTo(-38, 54);
    ctx.lineTo(-20, 24);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    drawLabel(ctx, "蜂鳥本體", centerX - 38, centerY - 58, "#bbf7d0");
    if (metrics.stability < 55) {
      drawArrow(ctx, 22, centerY - 18, 112, centerY - 18 + Math.sin(time * 0.01) * 10, "#facc15", "側風 / 漂移修正", { width: 2 });
    }

    if (showBrain) {
      const panelW = Math.min(342, width - 28);
      ctx.fillStyle = "rgba(7, 17, 22, 0.76)";
      roundedRect(ctx, 14, 14, panelW, 124, 12);
      ctx.fill();
      ctx.fillStyle = "rgba(255, 255, 255, 0.88)";
      ctx.font = "12px system-ui, sans-serif";
      ctx.fillText("即時估計", 28, 38);
      [
        "姿態誤差 / 視覺與前庭回授",
        "花朵位置、距離與風造成的漂移",
        "兩翼相位、振幅與左右不對稱修正",
        "升力、側風、肌肉延遲與疲勞取捨",
      ].forEach((line, index) => ctx.fillText(line, 28, 62 + index * 20));
    }
    drawLegend(ctx, [
      { color: "#10b981", label: "綠色：蜂鳥身體" },
      { color: "#a7f3d0", label: "綠線：下洗氣流" },
      { color: "#fecdd3", label: "粉色：花朵目標" },
    ], 14, Math.max(150, height - 106));
    ctx.fillStyle = "rgba(255, 255, 255, 0.68)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`慢動作顯示 ${metrics.visualHz.toFixed(1)} Hz · 真實翼拍 ${metrics.frequency.toFixed(0)} Hz`, 16, height - 18);

    setText("experiment-hummingbird-downwash", `${Math.round(metrics.downwash)}`);
    setText("experiment-hummingbird-balance", `${Math.round(metrics.balance)}%`);
    setText("experiment-hummingbird-cycle", `${metrics.trueCycleMs.toFixed(1)} ms`);
  }

  function drawWing(ctx, rootX, rootY, side, swingDeg, amplitude) {
    const length = 70 + amplitude * 0.55;
    const angle = (-35 * side + swingDeg * 0.7) * Math.PI / 180;
    const tipX = rootX + Math.cos(angle) * length * side;
    const tipY = rootY + Math.sin(angle) * length;
    ctx.save();
    ctx.fillStyle = "rgba(167, 243, 208, 0.2)";
    ctx.beginPath();
    ctx.moveTo(rootX, rootY);
    ctx.quadraticCurveTo(rootX + side * length * 0.38, rootY - 42, tipX, tipY);
    ctx.quadraticCurveTo(rootX + side * length * 0.28, rootY + 10, rootX, rootY + 8);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    ctx.beginPath();
    ctx.moveTo(rootX, rootY);
    ctx.quadraticCurveTo(rootX + side * length * 0.45, rootY - 24, tipX, tipY);
    ctx.stroke();
    ctx.strokeStyle = "rgba(108, 231, 183, 0.32)";
    ctx.lineWidth = 14;
    ctx.beginPath();
    ctx.moveTo(rootX, rootY);
    ctx.quadraticCurveTo(rootX + side * length * 0.45, rootY - 18, tipX, tipY);
    ctx.stroke();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.92)";
    ctx.lineWidth = 5;
  }

  function drawActiveStage(time, dt) {
    if (activeStage === "plane") drawPlane(time, dt);
    else if (activeStage === "liquid") drawLiquid(time, dt);
    else if (activeStage === "hummingbird") drawHummingbird(time, dt);
  }

  function frame(time) {
    const root = $("module-experiments");
    if (!root || !root.classList.contains("active") || document.hidden || paused) {
      rafId = 0;
      return;
    }
    const dt = lastFrameAt ? time - lastFrameAt : 16;
    lastFrameAt = time;
    if (!paused) drawActiveStage(time, dt);
    rafId = window.requestAnimationFrame(frame);
  }

  function startLoop() {
    if (rafId || paused) return;
    lastFrameAt = 0;
    rafId = window.requestAnimationFrame(frame);
  }

  function stopLoop() {
    if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = 0;
    }
    lastFrameAt = 0;
  }

  function setActiveStage(stage) {
    activeStage = stage || "plane";
    document.querySelectorAll("[data-experiment-stage]").forEach((node) => {
      if (node.classList.contains("experiment-stage")) {
        node.classList.toggle("active", node.dataset.experimentStage === activeStage);
      }
    });
    document.querySelectorAll("[data-experiment-tab]").forEach((button) => {
      const selected = button.dataset.experimentTab === activeStage;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-selected", selected ? "true" : "false");
    });
    resizeCanvases();
    drawActiveStage(performance.now(), 16);
  }

  function bindControls() {
    document.querySelectorAll(".experiment-control input, .experiment-control select").forEach((input) => {
      syncControlValue(input);
      const redraw = () => {
        syncControlValue(input);
        drawActiveStage(performance.now(), 16);
      };
      input.addEventListener("input", redraw);
      input.addEventListener("change", redraw);
    });
    document.querySelectorAll(".experiment-toggle input").forEach((input) => {
      input.addEventListener("change", () => drawActiveStage(performance.now(), 16));
    });
    document.querySelectorAll("[data-experiment-tab]").forEach((button) => {
      button.addEventListener("click", () => setActiveStage(button.dataset.experimentTab || "plane"));
    });
    const pauseButton = $("experiment-pause-toggle");
    if (pauseButton) {
      pauseButton.addEventListener("click", () => {
        paused = !paused;
        pauseButton.setAttribute("aria-pressed", paused ? "true" : "false");
        pauseButton.textContent = paused ? "繼續動畫" : "暫停動畫";
        if (paused) {
          stopLoop();
        } else {
          drawActiveStage(performance.now(), 16);
          startLoop();
        }
      });
    }
    const shakeButton = $("experiment-liquid-shake");
    if (shakeButton) {
      shakeButton.addEventListener("click", () => {
        state.liquid.shake = 1;
        drawActiveStage(performance.now(), 16);
      });
    }
    const stirButton = $("experiment-liquid-stir");
    if (stirButton) {
      stirButton.addEventListener("click", () => {
        state.liquid.stir = 1.5;
        state.liquid.shake = Math.max(state.liquid.shake, 0.18);
        drawActiveStage(performance.now(), 16);
      });
    }
    const pourButton = $("experiment-liquid-pour");
    if (pourButton) {
      pourButton.addEventListener("click", () => {
        const tilt = $("experiment-liquid-tilt");
        if (tilt) {
          tilt.value = "55";
          syncControlValue(tilt);
        }
        state.liquid.particles.forEach((p) => { p.vx += randomRange(0.01, 0.026); });
        drawActiveStage(performance.now(), 16);
      });
    }
    const dropButton = $("experiment-liquid-drop");
    if (dropButton) {
      dropButton.addEventListener("click", () => {
        state.liquid.objects.push({ x: randomRange(0.35, 0.65), y: 0.08, vx: 0, vy: 0.006, size: randomRange(12, 20) });
        if (state.liquid.objects.length > 8) state.liquid.objects.shift();
        drawActiveStage(performance.now(), 16);
      });
    }
    const resetButton = $("experiment-liquid-reset");
    if (resetButton) {
      resetButton.addEventListener("click", () => {
        const tilt = $("experiment-liquid-tilt");
        if (tilt) {
          tilt.value = "0";
          syncControlValue(tilt);
        }
        state.liquid.shake = 0;
        state.liquid.stir = 0;
        seedLiquidParticles();
        drawActiveStage(performance.now(), 16);
      });
    }
    window.addEventListener("resize", resizeCanvases, { passive: true });
    document.addEventListener("visibilitychange", () => {
      const root = $("module-experiments");
      if (!document.hidden && root && root.classList.contains("active")) startLoop();
    });
  }

  function initExperimentArea() {
    const root = $("module-experiments");
    if (!root) return;
    if (!state.plane.particles.length) seedPlaneParticles();
    if (!state.liquid.particles.length) seedLiquidParticles();
    if (!state.hummingbird.particles.length) seedHummingbirdParticles();
    if (!initialized) {
      initialized = true;
      bindControls();
    }
    resizeCanvases();
    setActiveStage(activeStage);
    startLoop();
  }

  window.initExperimentArea = initExperimentArea;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initExperimentArea, { once: true });
  } else {
    initExperimentArea();
  }
})();
