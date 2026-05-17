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
    liquid: { particles: [], objects: [], shake: 0, spilled: 0 },
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
      return { ctx: cached.ctx, width: cached.width, height: cached.height };
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
    return { ctx, width, height };
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

  function drawArrow(ctx, fromX, fromY, toX, toY, color, label) {
    const angle = Math.atan2(toY - fromY, toX - fromX);
    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 3;
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
      ctx.font = "12px system-ui, sans-serif";
      ctx.fillText(label, toX + 8, toY - 8);
    }
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

  function drawPlane(time, dt) {
    const info = canvasInfo("experiment-plane-canvas");
    if (!info) return;
    const { ctx, width, height } = info;
    const metrics = planeMetrics();
    const vortices = checkedValue("experiment-plane-vortices");
    const step = Math.min(dt || 16, 40) / 16.67;
    ctx.clearRect(0, 0, width, height);

    const sky = ctx.createLinearGradient(0, 0, 0, height);
    sky.addColorStop(0, "#12304d");
    sky.addColorStop(1, "#071217");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, width, height);

    const centerX = width * 0.52;
    const centerY = height * 0.52;
    const wingLength = Math.min(width * 0.44, 360);
    const flowSpeed = 0.0018 * metrics.relativeWind;
    state.plane.particles.forEach((p) => {
      p.x += flowSpeed * p.speed * step;
      if (p.x > 1.08) {
        p.x = -0.08;
        p.y = randomRange(0.12, 0.88);
        p.speed = randomRange(0.55, 1.25);
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
    ctx.restore();

    drawArrow(ctx, centerX, centerY - 22, centerX, centerY - 22 - metrics.lift * 0.75, "#6ee7b7", "lift");
    drawArrow(ctx, centerX - 18, centerY + 34, centerX - 18 - metrics.drag * 0.65, centerY + 34, "#fda4af", "drag");
    ctx.fillStyle = "rgba(255, 255, 255, 0.72)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`AoA ${metrics.aoa.toFixed(0)}° · relative airspeed ${metrics.relativeWind.toFixed(0)}`, 16, height - 18);

    setText("experiment-plane-lift", `${Math.round(metrics.lift)}`);
    setText("experiment-plane-drag", `${Math.round(metrics.drag)}`);
    setText("experiment-plane-stall", `${Math.round(metrics.stall)}%`);
  }

  function updateLiquid(time, dt) {
    const tilt = numberValue("experiment-liquid-tilt", 0);
    const viscosity = numberValue("experiment-liquid-viscosity", 0.45);
    const level = numberValue("experiment-liquid-level", 68) / 100;
    const top = 1 - level;
    const step = Math.min(dt || 16, 40) / 16.67;
    const tiltForce = Math.sin(tilt * Math.PI / 180) * 0.0032;
    state.liquid.shake = Math.max(0, state.liquid.shake - 0.03 * step);
    let energy = 0;

    state.liquid.particles.forEach((p, index) => {
      const shakeForce = state.liquid.shake * Math.sin(index * 1.7 + time * 0.025) * 0.004;
      p.vx += (tiltForce + shakeForce) * step;
      p.vy += 0.0009 * step;
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
      if (p.y < top + 0.02) {
        p.y = top + 0.02;
        p.vy = Math.abs(p.vy) * 0.18;
      }
      if (p.y > 0.96) {
        p.y = 0.96;
        p.vy = -Math.abs(p.vy) * 0.24;
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
      obj.vy += 0.0015 * step;
      obj.vx += tiltForce * 0.7 * step;
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
    const { ctx, width, height } = info;
    const tilt = numberValue("experiment-liquid-tilt", 0);
    const level = numberValue("experiment-liquid-level", 68) / 100;
    const top = 1 - level;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#08141d";
    ctx.fillRect(0, 0, width, height);

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
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const waterTopY = centerY + (top - 0.5) * cupHeight;
    const waterBottomY = centerY + cupHeight * 0.6;
    const waterGradient = ctx.createLinearGradient(0, waterTopY, 0, waterBottomY);
    waterGradient.addColorStop(0, "rgba(92, 225, 255, 0.28)");
    waterGradient.addColorStop(1, "rgba(38, 140, 255, 0.2)");
    ctx.fillStyle = waterGradient;
    ctx.fillRect(centerX - cupWidth * 0.72, waterTopY, cupWidth * 1.44, cupHeight * 1.1);
    state.liquid.particles.forEach((p) => {
      const px = centerX + (p.x - 0.5) * cupWidth;
      const py = centerY + (p.y - 0.5) * cupHeight;
      ctx.fillStyle = "rgba(120, 225, 255, 0.78)";
      ctx.beginPath();
      ctx.arc(px, py, p.r, 0, TWO_PI);
      ctx.fill();
    });
    state.liquid.objects.forEach((obj) => {
      const px = centerX + (obj.x - 0.5) * cupWidth;
      const py = centerY + (obj.y - 0.5) * cupHeight;
      ctx.fillStyle = "rgba(255, 214, 102, 0.88)";
      ctx.fillRect(px - obj.size / 2, py - obj.size / 2, obj.size, obj.size);
    });
    ctx.strokeStyle = "rgba(255, 255, 255, 0.22)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(centerX - cupWidth * 0.66, waterTopY);
    ctx.lineTo(centerX + cupWidth * 0.66, waterTopY);
    ctx.stroke();
    ctx.restore();

    ctx.strokeStyle = "rgba(255, 255, 255, 0.72)";
    ctx.lineWidth = 3;
    ctx.stroke(cupPath);
    ctx.restore();

    ctx.fillStyle = "rgba(255, 255, 255, 0.68)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`tilt ${tilt.toFixed(0)}° · visible ${state.liquid.particles.length} · spilled ${state.liquid.spilled}`, 16, height - 18);
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

    ctx.save();
    ctx.translate(width * 0.75, height * 0.42);
    ctx.strokeStyle = "rgba(255, 190, 210, 0.75)";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(0, 30);
    ctx.lineTo(0, height * 0.26);
    ctx.stroke();
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

    const wingSwing = Math.sin(metrics.phase * TWO_PI) * metrics.amplitude;
    const asymmetry = (100 - metrics.stability) * 0.18 * Math.sin(time * 0.004);
    ctx.save();
    ctx.translate(centerX, centerY);
    ctx.fillStyle = "rgba(245, 250, 255, 0.95)";
    ctx.beginPath();
    ctx.ellipse(0, 0, 18, 34, -0.16, 0, TWO_PI);
    ctx.fill();
    ctx.fillStyle = "rgba(132, 211, 255, 0.92)";
    ctx.beginPath();
    ctx.arc(4, -30, 14, 0, TWO_PI);
    ctx.fill();
    ctx.strokeStyle = "rgba(255, 255, 255, 0.92)";
    ctx.lineWidth = 5;
    drawWing(ctx, -8, -10, -1, wingSwing - asymmetry, metrics.amplitude);
    drawWing(ctx, 8, -10, 1, -wingSwing - asymmetry, metrics.amplitude);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.8)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(14, -30);
    ctx.lineTo(54, -38);
    ctx.stroke();
    ctx.restore();

    if (showBrain) {
      ctx.fillStyle = "rgba(7, 17, 22, 0.72)";
      ctx.fillRect(14, 14, Math.min(320, width - 28), 112);
      ctx.fillStyle = "rgba(255, 255, 255, 0.88)";
      ctx.font = "12px system-ui, sans-serif";
      [
        "姿態誤差 / 視覺與前庭回授",
        "花朵位置、距離與風造成的漂移",
        "兩翼相位、振幅與左右不對稱修正",
        "升力、側風、肌肉延遲與疲勞取捨",
      ].forEach((line, index) => ctx.fillText(line, 28, 40 + index * 22));
    }
    ctx.fillStyle = "rgba(255, 255, 255, 0.68)";
    ctx.font = "12px system-ui, sans-serif";
    ctx.fillText(`visual slow motion ${metrics.visualHz.toFixed(1)} Hz · true ${metrics.frequency.toFixed(0)} Hz`, 16, height - 18);

    setText("experiment-hummingbird-downwash", `${Math.round(metrics.downwash)}`);
    setText("experiment-hummingbird-balance", `${Math.round(metrics.balance)}%`);
    setText("experiment-hummingbird-cycle", `${metrics.trueCycleMs.toFixed(1)} ms`);
  }

  function drawWing(ctx, rootX, rootY, side, swingDeg, amplitude) {
    const length = 70 + amplitude * 0.55;
    const angle = (-35 * side + swingDeg * 0.7) * Math.PI / 180;
    const tipX = rootX + Math.cos(angle) * length * side;
    const tipY = rootY + Math.sin(angle) * length;
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
    document.querySelectorAll(".experiment-control input").forEach((input) => {
      syncControlValue(input);
      input.addEventListener("input", () => {
        syncControlValue(input);
        drawActiveStage(performance.now(), 16);
      });
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
