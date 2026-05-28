'use strict';

(function setupExperimentArea() {
  function experimentPerformanceProfile() {
    const cores = Math.max(1, Number(navigator.hardwareConcurrency || 4));
    const reducedMotion = !!window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (reducedMotion || cores <= 2) return { planeParticles: 72, liquidParticles: 110, dprCap: 1.15 };
    if (cores <= 4) return { planeParticles: 112, liquidParticles: 170, dprCap: 1.35 };
    return { planeParticles: 160, liquidParticles: 240, dprCap: 1.6 };
  }

  const EXPERIMENT_PERFORMANCE_PROFILE = experimentPerformanceProfile();
  const PLANE_PARTICLE_COUNT = EXPERIMENT_PERFORMANCE_PROFILE.planeParticles;
  const LIQUID_PARTICLE_COUNT = EXPERIMENT_PERFORMANCE_PROFILE.liquidParticles;
  const EXPERIMENT_DPR_CAP = EXPERIMENT_PERFORMANCE_PROFILE.dprCap;
  const TWO_PI = Math.PI * 2;
  let initialized = false;
  let rafId = 0;
  let lastFrameAt = 0;
  let activeStage = "plane";
  let running = false;
  const canvasSizeCache = new Map();

  const state = {
    plane: {
      particles: [],
      scene3d: null,
      sceneLoading: null,
      sceneError: null,
      orbitBound: false,
      lastViewPreset: null,
      view: { yaw: 0.82, pitch: 0.34, distance: 8.4, dragging: false, pointerId: null, lastX: 0, lastY: 0 },
    },
    liquid: { particles: [], objects: [], shake: 0, stir: 0, spilled: 0 },
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
    const dpr = Math.min(window.devicePixelRatio || 1, EXPERIMENT_DPR_CAP);
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

  function planeCanvasSize() {
    const canvas = $("experiment-plane-canvas");
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const fallbackWidth = canvas.parentElement ? canvas.parentElement.clientWidth : 640;
    const width = Math.max(300, Math.round(rect.width || fallbackWidth || 640));
    const height = Math.max(280, Math.round(rect.height || 420));
    const dpr = Math.min(window.devicePixelRatio || 1, EXPERIMENT_DPR_CAP);
    if (!state.plane.scene3d) {
      const targetWidth = Math.round(width * dpr);
      const targetHeight = Math.round(height * dpr);
      if (canvas.width !== targetWidth) canvas.width = targetWidth;
      if (canvas.height !== targetHeight) canvas.height = targetHeight;
    }
    return { canvas, width, height, dpr };
  }

  function resizePlaneScene(force = false) {
    const info = planeCanvasSize();
    const plane = state.plane.scene3d;
    if (!info || !plane) return info;
    if (!force && plane.width === info.width && plane.height === info.height && plane.dpr === info.dpr) return info;
    plane.width = info.width;
    plane.height = info.height;
    plane.dpr = info.dpr;
    plane.renderer.setPixelRatio(info.dpr);
    plane.renderer.setSize(info.width, info.height, false);
    plane.camera.aspect = info.width / info.height;
    plane.camera.updateProjectionMatrix();
    return info;
  }

  function resizeCanvases() {
    resizePlaneScene(true);
    resizeCanvas($("experiment-liquid-canvas"), true);
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
    state.liquid.particles = Array.from({ length: LIQUID_PARTICLE_COUNT }, () => {
      const x = randomRange(0.04, 0.96);
      const y = randomRange(0.04, 0.96);
      return {
        x,
        y,
        vx: randomRange(-0.002, 0.002),
        vy: randomRange(-0.002, 0.002),
        homeX: x,
        homeY: y,
        phase: Math.random() * TWO_PI,
        r: randomRange(1.4, 2.8),
      };
    });
    state.liquid.objects = [];
    state.liquid.shake = 0;
    state.liquid.stir = 0;
    state.liquid.spilled = 0;
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

  function setPlaneOverlay(visible, title = "", detail = "") {
    const overlay = $("experiment-plane-overlay");
    if (!overlay) return;
    overlay.hidden = !visible;
    setText("experiment-plane-overlay-title", title);
    setText("experiment-plane-overlay-detail", detail);
  }

  function planePresetAngles(view) {
    if (view === "top") return { yaw: Math.PI / 2, pitch: 1.1 };
    if (view === "front") return { yaw: 0.05, pitch: 0.18 };
    if (view === "side") return { yaw: Math.PI / 2, pitch: 0.16 };
    return { yaw: 0.82, pitch: 0.34 };
  }

  function applyPlaneViewPreset(view, force = false) {
    const normalized = view || planeViewMode();
    if (!force && state.plane.lastViewPreset === normalized) return;
    const preset = planePresetAngles(normalized);
    state.plane.view.yaw = preset.yaw;
    state.plane.view.pitch = preset.pitch;
    state.plane.lastViewPreset = normalized;
  }

  function orientThreeObject(THREE, object, direction) {
    const from = new THREE.Vector3(0, 1, 0);
    const to = direction.clone().normalize();
    object.quaternion.setFromUnitVectors(from, to);
  }

  function createPlaneForceArrow(THREE, color) {
    const group = new THREE.Group();
    const material = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.88, depthWrite: false });
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 1, 10), material);
    const head = new THREE.Mesh(new THREE.ConeGeometry(0.105, 0.34, 14), material);
    shaft.name = "shaft";
    head.name = "head";
    group.add(shaft, head);
    return group;
  }

  function updatePlaneForceArrow(THREE, group, origin, direction, length) {
    if (!group) return;
    const shaft = group.getObjectByName("shaft");
    const head = group.getObjectByName("head");
    const safeLength = clamp(length, 0.2, 2.4);
    group.visible = safeLength > 0.18;
    group.position.copy(origin);
    orientThreeObject(THREE, group, direction);
    if (shaft) {
      shaft.scale.set(1, safeLength, 1);
      shaft.position.set(0, safeLength / 2, 0);
    }
    if (head) head.position.set(0, safeLength + 0.18, 0);
  }

  function createAirflowTriangles(THREE) {
    const geometry = new THREE.ConeGeometry(0.085, 0.34, 3, 1, false);
    const arrows = [];
    const rows = [-1.0, -0.48, 0.08, 0.62, 1.12];
    const lanes = [-2.55, -1.25, 0, 1.25, 2.55];
    rows.forEach((baseY, rowIndex) => {
      lanes.forEach((baseZ, laneIndex) => {
        for (let step = 0; step < 4; step += 1) {
          const material = new THREE.MeshBasicMaterial({
            color: 0x76d2ff,
            transparent: true,
            opacity: 0.62,
            depthWrite: false,
          });
          const mesh = new THREE.Mesh(geometry, material);
          mesh.userData = {
            baseX: step * 2.72 + rowIndex * 0.28 + laneIndex * 0.19,
            baseY,
            baseZ,
            rowIndex,
            laneIndex,
            speed: randomRange(0.75, 1.28),
            phase: randomRange(0, TWO_PI),
          };
          arrows.push(mesh);
        }
      });
    });
    return arrows;
  }

  function buildPlaneScene(THREE, canvas) {
    const renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setClearColor(0x000000, 0);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(44, 1, 0.1, 80);
    const planeRoot = new THREE.Group();
    scene.add(planeRoot);

    scene.add(new THREE.HemisphereLight(0xd8f4ff, 0x253245, 1.9));
    const sun = new THREE.DirectionalLight(0xffffff, 1.35);
    sun.position.set(4, 6, 3);
    scene.add(sun);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(12, 8),
      new THREE.MeshBasicMaterial({ color: 0x123b44, transparent: true, opacity: 0.28, side: THREE.DoubleSide }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -1.45;
    scene.add(ground);

    const fuselageMaterial = new THREE.MeshStandardMaterial({ color: 0xe7eef8, metalness: 0.12, roughness: 0.42 });
    const wingMaterial = new THREE.MeshStandardMaterial({ color: 0x98b7d9, metalness: 0.08, roughness: 0.48 });
    const accentMaterial = new THREE.MeshStandardMaterial({ color: 0x4f9cff, metalness: 0.1, roughness: 0.42 });
    const warningMaterial = new THREE.MeshStandardMaterial({ color: 0xff7b54, metalness: 0.04, roughness: 0.45 });
    const glassMaterial = new THREE.MeshStandardMaterial({ color: 0x5fd7ff, transparent: true, opacity: 0.58, roughness: 0.1 });

    const fuselage = new THREE.Mesh(new THREE.CylinderGeometry(0.23, 0.31, 3.2, 22), fuselageMaterial);
    fuselage.rotation.z = Math.PI / 2;
    planeRoot.add(fuselage);
    const nose = new THREE.Mesh(new THREE.ConeGeometry(0.25, 0.62, 22), fuselageMaterial);
    nose.rotation.z = -Math.PI / 2;
    nose.position.x = 1.92;
    planeRoot.add(nose);
    const tailCone = new THREE.Mesh(new THREE.ConeGeometry(0.24, 0.5, 18), fuselageMaterial);
    tailCone.rotation.z = Math.PI / 2;
    tailCone.position.x = -1.84;
    planeRoot.add(tailCone);
    const cockpit = new THREE.Mesh(new THREE.SphereGeometry(0.27, 18, 10), glassMaterial);
    cockpit.scale.set(1.25, 0.46, 0.64);
    cockpit.position.set(0.72, 0.25, 0);
    planeRoot.add(cockpit);

    const wing = new THREE.Mesh(new THREE.BoxGeometry(1.22, 0.075, 4.72), wingMaterial);
    wing.position.set(-0.08, -0.02, 0);
    planeRoot.add(wing);
    const leftFlap = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.045, 1.72), accentMaterial);
    leftFlap.position.set(-0.78, -0.06, -1.38);
    const rightFlap = leftFlap.clone();
    rightFlap.position.z = 1.38;
    planeRoot.add(leftFlap, rightFlap);

    const leftSpoiler = new THREE.Mesh(new THREE.BoxGeometry(0.26, 0.04, 1.1), warningMaterial);
    leftSpoiler.position.set(-0.25, 0.055, -1.45);
    const rightSpoiler = leftSpoiler.clone();
    rightSpoiler.position.z = 1.45;
    planeRoot.add(leftSpoiler, rightSpoiler);

    const horizontalTail = new THREE.Mesh(new THREE.BoxGeometry(0.58, 0.055, 1.55), wingMaterial);
    horizontalTail.position.set(-1.48, 0.05, 0);
    planeRoot.add(horizontalTail);
    const verticalTail = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.88, 0.07), wingMaterial);
    verticalTail.position.set(-1.46, 0.42, 0);
    verticalTail.rotation.z = -0.23;
    planeRoot.add(verticalTail);

    const airflowGroup = new THREE.Group();
    const airflowArrows = createAirflowTriangles(THREE);
    airflowArrows.forEach((arrow) => airflowGroup.add(arrow));
    scene.add(airflowGroup);

    const liftArrow = createPlaneForceArrow(THREE, 0x74f0b6);
    const dragArrow = createPlaneForceArrow(THREE, 0xff9aa9);
    scene.add(liftArrow, dragArrow);

    const vortexGroup = new THREE.Group();
    const vortexMaterial = new THREE.MeshBasicMaterial({ color: 0xfbbf24, transparent: true, opacity: 0.55, side: THREE.DoubleSide });
    for (let i = 0; i < 8; i += 1) {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.18 + i * 0.018, 0.012, 6, 24), vortexMaterial);
      ring.userData = { side: i < 4 ? -1 : 1, step: i % 4 };
      vortexGroup.add(ring);
    }
    scene.add(vortexGroup);

    return {
      THREE,
      renderer,
      scene,
      camera,
      planeRoot,
      leftFlap,
      rightFlap,
      leftSpoiler,
      rightSpoiler,
      airflowArrows,
      airflowGroup,
      liftArrow,
      dragArrow,
      vortexGroup,
      wingMaterial,
      width: 0,
      height: 0,
      dpr: 0,
    };
  }

  function updatePlaneCamera(plane) {
    const { THREE, camera } = plane;
    const view = state.plane.view;
    const distance = view.distance;
    const pitch = clamp(view.pitch, -0.18, 1.22);
    const yaw = view.yaw;
    camera.position.set(
      Math.cos(pitch) * Math.cos(yaw) * distance,
      Math.sin(pitch) * distance,
      Math.cos(pitch) * Math.sin(yaw) * distance,
    );
    camera.lookAt(new THREE.Vector3(0, 0.05, 0));
  }

  function updateAirflowTriangles(plane, metrics, time) {
    const { THREE } = plane;
    const range = 10.9;
    const shift = running ? (time * 0.00062 * Math.max(15, metrics.relativeWind)) : 0;
    const vortices = checkedValue("experiment-plane-vortices");
    plane.airflowArrows.forEach((arrow) => {
      const data = arrow.userData;
      const laneX = 5.1 - ((data.baseX + shift * data.speed) % range);
      const wingInfluence = clamp(1 - Math.abs(laneX + 0.05) / 2.35, 0, 1) * clamp(1 - Math.abs(data.baseZ) / 2.85, 0, 1);
      const tipInfluence = vortices ? clamp(1 - Math.abs(Math.abs(data.baseZ) - 2.38) / 0.78, 0, 1) * clamp(1 - Math.abs(laneX) / 2.7, 0, 1) : 0;
      const stallNoise = metrics.stall > 44 ? (metrics.stall - 44) / 56 : 0;
      const flutter = Math.sin(time * 0.006 + data.phase + data.rowIndex * 0.7) * (0.05 + stallNoise * 0.18 + (metrics.spoiler ? 0.08 : 0));
      const downwash = -0.035 - wingInfluence * (metrics.effectiveAoa * 0.008 + metrics.flap * 0.004 + stallNoise * 0.15);
      const side = data.baseZ >= 0 ? 1 : -1;
      const swirl = tipInfluence * side * Math.sin(time * 0.01 + data.phase + laneX) * (0.12 + metrics.relativeWind / 430);
      const direction = new THREE.Vector3(-1, downwash + flutter * wingInfluence, swirl).normalize();
      const intensity = clamp((metrics.relativeWind / 92) * (0.68 + wingInfluence * 0.72 + tipInfluence * 0.42 + stallNoise * 0.32), 0.34, 2.15);
      arrow.position.set(
        laneX,
        data.baseY + wingInfluence * downwash * 1.6 + flutter,
        data.baseZ + tipInfluence * side * Math.sin(time * 0.011 + data.phase) * 0.26,
      );
      orientThreeObject(THREE, arrow, direction);
      arrow.scale.setScalar(0.68 + intensity * 0.44);
      arrow.material.opacity = clamp(0.34 + intensity * 0.27, 0.34, 0.92);
      if (stallNoise > 0.35 && wingInfluence > 0.28) arrow.material.color.set(0xffb15f);
      else if (tipInfluence > 0.35) arrow.material.color.set(0xfbd35f);
      else arrow.material.color.set(0x76d2ff);
    });
  }

  function updatePlaneModel(plane, metrics, time) {
    const { THREE } = plane;
    plane.planeRoot.rotation.z = metrics.aoa * Math.PI / 180 * 0.32;
    const flapAngle = -metrics.flap * Math.PI / 180 * 0.86;
    plane.leftFlap.rotation.z = flapAngle;
    plane.rightFlap.rotation.z = flapAngle;
    plane.leftSpoiler.visible = metrics.spoiler;
    plane.rightSpoiler.visible = metrics.spoiler;
    plane.leftSpoiler.rotation.z = metrics.spoiler ? Math.PI / 4 : 0;
    plane.rightSpoiler.rotation.z = metrics.spoiler ? Math.PI / 4 : 0;
    const stallTint = metrics.stall / 100;
    plane.wingMaterial.color.set(stallTint > 0.62 ? 0xffaf6b : 0x98b7d9);
    updateAirflowTriangles(plane, metrics, time);
    updatePlaneForceArrow(THREE, plane.liftArrow, new THREE.Vector3(-0.12, 0.26, 0), new THREE.Vector3(0, 1, 0), metrics.lift / 88);
    updatePlaneForceArrow(THREE, plane.dragArrow, new THREE.Vector3(-0.28, -0.26, 0), new THREE.Vector3(-1, -0.08, 0), metrics.drag / 118);
    const showVortices = checkedValue("experiment-plane-vortices");
    plane.vortexGroup.visible = showVortices;
    plane.vortexGroup.children.forEach((ring) => {
      const side = ring.userData.side;
      const step = ring.userData.step;
      ring.position.set(-1.35 - step * 0.34, -0.08 - step * 0.07, side * (2.36 + step * 0.06));
      ring.rotation.set(Math.PI / 2 + time * 0.002 * side, time * 0.004 + step * 0.6, 0);
      ring.scale.setScalar(1 + step * 0.14 + metrics.relativeWind / 360);
    });
    updatePlaneCamera(plane);
  }

  function renderPlaneScene(time, dt, metrics) {
    const plane = state.plane.scene3d;
    if (!plane) return false;
    resizePlaneScene(false);
    updatePlaneModel(plane, metrics, time + (dt || 0));
    plane.renderer.render(plane.scene, plane.camera);
    setPlaneOverlay(false);
    return true;
  }

  function ensurePlaneScene() {
    if (state.plane.scene3d) return Promise.resolve(state.plane.scene3d);
    if (state.plane.sceneLoading) return state.plane.sceneLoading;
    const canvas = $("experiment-plane-canvas");
    if (!canvas) return Promise.resolve(null);
    state.plane.sceneError = null;
    setPlaneOverlay(true, "正在載入 3D 飛機模型", "載入完成後可用滑鼠拖曳或觸控滑動旋轉視角；三角形越大越亮，代表該處氣流越強。");
    const loader = typeof ensureThreeJsLoaded === "function" ? ensureThreeJsLoaded() : Promise.resolve(window.THREE || null);
    state.plane.sceneLoading = loader
      .then((THREE) => {
        if (!THREE) throw new Error("Three.js unavailable");
        const scene3d = buildPlaneScene(THREE, canvas);
        state.plane.scene3d = scene3d;
        applyPlaneViewPreset(planeViewMode(), true);
        resizePlaneScene(true);
        renderPlaneScene(performance.now(), 16, planeMetrics());
        return scene3d;
      })
      .catch((error) => {
        state.plane.sceneError = error;
        console.error("Experiment plane 3D scene failed to load", error);
        setPlaneOverlay(true, "3D 飛機模型載入失敗", "目前瀏覽器無法建立 WebGL 場景，請確認瀏覽器或顯示卡設定。");
        return null;
      })
      .finally(() => {
        state.plane.sceneLoading = null;
      });
    return state.plane.sceneLoading;
  }

  function bindPlaneOrbitControls() {
    const canvas = $("experiment-plane-canvas");
    if (!canvas || state.plane.orbitBound) return;
    state.plane.orbitBound = true;
    const releaseDrag = () => {
      state.plane.view.dragging = false;
      state.plane.view.pointerId = null;
      canvas.classList.remove("experiment-plane-dragging");
    };
    canvas.addEventListener("pointerdown", (event) => {
      if (event.button !== undefined && event.button !== 0) return;
      state.plane.view.dragging = true;
      state.plane.view.pointerId = event.pointerId;
      state.plane.view.lastX = event.clientX;
      state.plane.view.lastY = event.clientY;
      canvas.classList.add("experiment-plane-dragging");
      try { canvas.setPointerCapture(event.pointerId); } catch (_) {}
      if (state.plane.scene3d) renderPlaneScene(performance.now(), 16, planeMetrics());
      else if (running) ensurePlaneScene();
      else setPlaneOverlay(true, "按下開始載入 3D 飛機模型", "開始後可拖曳或滑動旋轉視角，氣流三角形會同步顯示方向與強度。");
      event.preventDefault();
    }, { passive: false });
    canvas.addEventListener("pointermove", (event) => {
      const view = state.plane.view;
      if (!view.dragging || view.pointerId !== event.pointerId) return;
      const dx = event.clientX - view.lastX;
      const dy = event.clientY - view.lastY;
      view.lastX = event.clientX;
      view.lastY = event.clientY;
      view.yaw -= dx * 0.008;
      view.pitch = clamp(view.pitch + dy * 0.006, -0.18, 1.22);
      if (state.plane.scene3d) renderPlaneScene(performance.now(), 16, planeMetrics());
      event.preventDefault();
    }, { passive: false });
    canvas.addEventListener("pointerup", releaseDrag);
    canvas.addEventListener("pointercancel", releaseDrag);
    canvas.addEventListener("lostpointercapture", releaseDrag);
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
    const metrics = planeMetrics();
    updatePlaneKpis(metrics);
    planeCanvasSize();
    if (state.plane.lastViewPreset !== planeViewMode() && !state.plane.view.dragging) {
      applyPlaneViewPreset(planeViewMode(), false);
    }
    if (state.plane.scene3d) {
      renderPlaneScene(time, dt, metrics);
      return;
    }
    if (state.plane.sceneLoading) {
      setPlaneOverlay(true, "正在載入 3D 飛機模型", "載入後即可用滑鼠拖曳或觸控滑動控制視角。");
      return;
    }
    if (state.plane.sceneError) {
      setPlaneOverlay(true, "3D 飛機模型載入失敗", "目前瀏覽器無法建立 WebGL 場景，請確認瀏覽器或顯示卡設定。");
      return;
    }
    if (running) {
      ensurePlaneScene();
      return;
    }
    setPlaneOverlay(true, "按下開始載入 3D 飛機模型", "飛機頁不會自動啟動 3D 模擬；開始後可拖曳或滑動視角，三角形代表氣流方向與強度。");
  }

  function liquidCupGeometry(width, height, tilt) {
    const cupWidth = Math.min(width * 0.58, 390);
    const cupHeight = Math.min(height * 0.74, 330);
    const centerX = width * 0.5;
    const centerY = height * 0.54;
    const angle = tilt * Math.PI / 180 * 0.58;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const toScreen = (x, y) => ({
      x: centerX + x * cos - y * sin,
      y: centerY + x * sin + y * cos,
    });
    const points = [
      toScreen(-cupWidth * 0.56, -cupHeight * 0.5),
      toScreen(cupWidth * 0.56, -cupHeight * 0.5),
      toScreen(cupWidth * 0.39, cupHeight * 0.5),
      toScreen(-cupWidth * 0.39, cupHeight * 0.5),
    ];
    const ys = points.map((p) => p.y);
    const xs = points.map((p) => p.x);
    return {
      centerX,
      centerY,
      cupWidth,
      cupHeight,
      angle,
      points,
      minX: Math.min(...xs),
      maxX: Math.max(...xs),
      minY: Math.min(...ys),
      maxY: Math.max(...ys),
    };
  }

  function buildPolygonPath(points) {
    const path = new Path2D();
    if (!points.length) return path;
    path.moveTo(points[0].x, points[0].y);
    points.slice(1).forEach((point) => path.lineTo(point.x, point.y));
    path.closePath();
    return path;
  }

  function polygonBoundsAtY(points, y) {
    const hits = [];
    for (let i = 0; i < points.length; i += 1) {
      const a = points[i];
      const b = points[(i + 1) % points.length];
      if ((a.y <= y && b.y > y) || (b.y <= y && a.y > y)) {
        const t = (y - a.y) / (b.y - a.y);
        hits.push(a.x + (b.x - a.x) * t);
      }
    }
    if (hits.length < 2) return null;
    hits.sort((a, b) => a - b);
    return { left: hits[0], right: hits[hits.length - 1] };
  }

  function liquidSurfaceY(geometry, level) {
    const innerTop = geometry.minY + 10;
    const innerBottom = geometry.maxY - 14;
    return innerBottom - clamp(level, 0.05, 0.96) * (innerBottom - innerTop);
  }

  function liquidParticleScreenPosition(p, geometry, surfaceY, time) {
    const ySpan = Math.max(24, geometry.maxY - surfaceY - 12);
    const wave = Math.sin(time * 0.006 + (p.phase || 0)) * (state.liquid.shake * 4 + state.liquid.stir * 2.5) * (1 - p.y * 0.55);
    const y = clamp(surfaceY + p.y * ySpan + wave, surfaceY + 6, geometry.maxY - 15);
    const bounds = polygonBoundsAtY(geometry.points, y);
    if (!bounds) return null;
    const pad = 12;
    const width = Math.max(4, bounds.right - bounds.left - pad * 2);
    const x = bounds.left + pad + clamp(p.x, 0, 1) * width;
    return { x, y };
  }

  function updateLiquid(time, dt) {
    const tilt = numberValue("experiment-liquid-tilt", 0);
    const viscosity = numberValue("experiment-liquid-viscosity", 0.45);
    const step = Math.min(dt || 16, 40) / 16.67;
    const tiltBias = Math.sin(tilt * Math.PI / 180);
    const damping = clamp(0.992 - viscosity * 0.05, 0.88, 0.985);
    const thermalScale = clamp(0.0026 - viscosity * 0.0012 + state.liquid.shake * 0.0012 + state.liquid.stir * 0.0011, 0.00055, 0.004);
    const homePull = clamp(0.0012 - viscosity * 0.00045, 0.00045, 0.00125);
    const stirStrength = state.liquid.stir * clamp(1.18 - viscosity * 0.42, 0.55, 1.15);
    let energy = 0;

    state.liquid.shake = Math.max(0, state.liquid.shake - 0.026 * step);
    state.liquid.stir = Math.max(0, state.liquid.stir - 0.009 * step);

    state.liquid.particles.forEach((p, index) => {
      if (!Number.isFinite(p.homeX)) p.homeX = clamp(p.x, 0.04, 0.96);
      if (!Number.isFinite(p.homeY)) p.homeY = clamp(p.y, 0.04, 0.96);
      if (!Number.isFinite(p.phase)) p.phase = index * 2.399;
      const dx = p.x - 0.5;
      const dy = p.y - 0.52;
      const distance = Math.sqrt(dx * dx + dy * dy);
      const swirl = clamp(1 - distance / 0.48, 0, 1) * stirStrength;
      const phase = time * 0.0026 + p.phase;
      const lowSideShift = tiltBias * 0.11 * (1 - p.y);
      const targetX = clamp(p.homeX + lowSideShift + Math.sin(time * 0.002 + p.phase) * state.liquid.shake * 0.045, 0.03, 0.97);
      const targetY = clamp(p.homeY + Math.cos(time * 0.0017 + p.phase) * state.liquid.shake * 0.035, 0.03, 0.97);
      p.vx += (targetX - p.x) * homePull * step;
      p.vy += (targetY - p.y) * homePull * 0.82 * step;
      p.vx += tiltBias * (0.00022 + state.liquid.shake * 0.00038) * (1 - viscosity * 0.28) * step;
      p.vx += (-dy * swirl * 0.009 - dx * swirl * 0.0015) * step;
      p.vy += (dx * swirl * 0.006 - dy * swirl * 0.0018) * step;
      p.vx += Math.sin(phase) * thermalScale * step;
      p.vy += Math.cos(phase * 1.31) * thermalScale * 0.8 * step;
      p.vx *= damping;
      p.vy *= damping;
      p.x += p.vx * step;
      p.y += p.vy * step;
      if (p.x < 0.018) {
        p.x = 0.018;
        p.vx = Math.abs(p.vx) * 0.52;
      } else if (p.x > 0.982) {
        p.x = 0.982;
        p.vx = -Math.abs(p.vx) * 0.52;
      }
      if (p.y < 0.018) {
        p.y = 0.018;
        p.vy = Math.abs(p.vy) * 0.48;
      } else if (p.y > 0.982) {
        p.y = 0.982;
        p.vy = -Math.abs(p.vy) * 0.48;
      }
      energy += p.vx * p.vx + p.vy * p.vy;
    });

    if (running && Math.abs(tilt) > 49 && state.liquid.particles.length > 72) {
      const spillSide = tilt > 0 ? 1 : -1;
      let removed = 0;
      state.liquid.particles = state.liquid.particles.filter((p) => {
        if (removed >= 3) return true;
        const nearLowerRim = spillSide > 0 ? p.x > 0.78 : p.x < 0.22;
        const nearSurface = p.y < 0.26;
        if (nearLowerRim && nearSurface && Math.random() < 0.38) {
          removed += 1;
          return false;
        }
        return true;
      });
      state.liquid.spilled += removed;
      if (removed > 0) {
        state.liquid.objects.forEach((obj) => {
          obj.vx += spillSide * 0.0045 * removed;
        });
      }
    }

    state.liquid.objects.forEach((obj) => {
      const dx = obj.x - 0.5;
      const dy = obj.y - 0.54;
      const swirl = clamp(1 - Math.sqrt(dx * dx + dy * dy) / 0.48, 0, 1) * stirStrength;
      obj.vy += 0.0019 * step;
      obj.vx += tiltBias * 0.0008 * step;
      obj.vx += -dy * swirl * 0.0065 * step;
      obj.vy += dx * swirl * 0.0038 * step;
      obj.vx *= 0.985;
      obj.vy *= 0.982;
      obj.x = clamp(obj.x + obj.vx * step, 0.06, 0.94);
      obj.y = clamp(obj.y + obj.vy * step, 0.08, 0.94);
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
    const geometry = liquidCupGeometry(width, height, tilt);
    const cupPath = buildPolygonPath(geometry.points);
    const surfaceY = liquidSurfaceY(geometry, level);
    const waterMinX = geometry.minX - 24;
    const waterMaxX = geometry.maxX + 24;
    const waveAmplitude = 3 + state.liquid.shake * 8 + state.liquid.stir * 5;

    ctx.clearRect(0, 0, width, height);
    const bg = ctx.createLinearGradient(0, 0, 0, height);
    bg.addColorStop(0, "#0d2334");
    bg.addColorStop(0.72, "#08141d");
    bg.addColorStop(1, "#0b1114");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = "rgba(255, 255, 255, 0.08)";
    ctx.fillRect(0, height * 0.78, width, height * 0.22);

    ctx.save();
    ctx.clip(cupPath);
    const waterGradient = ctx.createLinearGradient(0, surfaceY, 0, geometry.maxY);
    waterGradient.addColorStop(0, "rgba(92, 225, 255, 0.32)");
    waterGradient.addColorStop(1, "rgba(38, 140, 255, 0.2)");
    ctx.fillStyle = waterGradient;
    ctx.beginPath();
    for (let i = 0; i <= 44; i += 1) {
      const x = waterMinX + (waterMaxX - waterMinX) * (i / 44);
      const y = surfaceY + Math.sin(time * 0.008 + i * 0.62) * waveAmplitude;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.lineTo(waterMaxX, geometry.maxY + 28);
    ctx.lineTo(waterMinX, geometry.maxY + 28);
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = "rgba(180, 245, 255, 0.9)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i <= 44; i += 1) {
      const x = waterMinX + (waterMaxX - waterMinX) * (i / 44);
      const y = surfaceY + Math.sin(time * 0.008 + i * 0.62) * waveAmplitude;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    state.liquid.particles.forEach((p) => {
      const pos = liquidParticleScreenPosition(p, geometry, surfaceY, time);
      if (!pos) return;
      ctx.strokeStyle = "rgba(183, 245, 255, 0.22)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pos.x - p.vx * 2300, pos.y - p.vy * 2300);
      ctx.lineTo(pos.x, pos.y);
      ctx.stroke();
      ctx.fillStyle = "rgba(120, 225, 255, 0.84)";
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, p.r + 0.4, 0, TWO_PI);
      ctx.fill();
    });

    state.liquid.objects.forEach((obj) => {
      const pos = liquidParticleScreenPosition(obj, geometry, surfaceY, time);
      if (!pos) return;
      ctx.fillStyle = "rgba(255, 214, 102, 0.9)";
      roundedRect(ctx, pos.x - obj.size / 2, pos.y - obj.size / 2, obj.size, obj.size, 4);
      ctx.fill();
      ctx.strokeStyle = "rgba(255, 255, 255, 0.45)";
      ctx.stroke();
    });

    if (state.liquid.stir > 0.02) {
      const stirVisual = state.liquid.stir;
      const rodX = geometry.centerX + Math.sin(time * 0.008) * geometry.cupWidth * 0.08;
      const rodTopY = surfaceY - geometry.cupHeight * 0.32;
      const rodBottomY = surfaceY + geometry.cupHeight * 0.48;
      const rodTilt = Math.sin(time * 0.006) * geometry.cupWidth * 0.08;
      ctx.save();
      ctx.strokeStyle = "rgba(219, 242, 255, 0.58)";
      ctx.lineWidth = 9;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(rodX - rodTilt, rodTopY);
      ctx.lineTo(rodX + rodTilt, rodBottomY);
      ctx.stroke();
      ctx.strokeStyle = "rgba(255, 255, 255, 0.84)";
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
        ctx.ellipse(rodX, surfaceY + geometry.cupHeight * 0.24, radius, radius * 0.32, Math.sin(time * 0.006) * 0.25, time * 0.006 + i, time * 0.006 + i + Math.PI * 1.35);
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
      const y = geometry.minY + (geometry.maxY - geometry.minY) * (i / 6);
      const bounds = polygonBoundsAtY(geometry.points, y);
      if (!bounds) continue;
      ctx.beginPath();
      ctx.moveTo(bounds.left + 12, y);
      ctx.lineTo(bounds.left + 34, y);
      ctx.stroke();
    }

    drawLabel(ctx, "水平液面", geometry.centerX - geometry.cupWidth * 0.33, surfaceY - 12, "#bae6fd");
    drawLabel(ctx, "杯壁會傾斜，液面仍接近水平", geometry.minX + 14, geometry.maxY + 18, "#e0f2fe");
    drawArrow(ctx, width - 64, 54, width - 64, 128, "#fbbf24", "重力", { labelX: width - 116, labelY: 92, width: 2 });
    if (Math.abs(tilt) > 35 || state.liquid.spilled > 0) {
      const side = tilt >= 0 ? 1 : -1;
      const spillX = side > 0 ? geometry.maxX - 22 : geometry.minX + 22;
      const spillY = geometry.minY + geometry.cupHeight * 0.26;
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
      drawLabel(ctx, "傾角過大：運行時會逐步倒出", spillX + side * 18, spillY + 8, "#93c5fd");
    }
    drawLegend(ctx, [
      { color: "#78e1ff", label: "藍點：中性浮力懸浮分子" },
      { color: "#ffd666", label: "黃色：丟入物品會下沉" },
      { color: "#dbeafe", label: "半透明：玻璃棒攪拌" },
      { color: "#fbbf24", label: "箭頭：重力方向" },
    ], 14, 16);
    ctx.fillStyle = "rgba(255, 255, 255, 0.68)";
    ctx.font = "12px system-ui, sans-serif";
    const stirLabel = state.liquid.stir > 0.04 ? " · 玻璃棒攪拌中" : "";
    ctx.fillText(`杯子傾角 ${tilt.toFixed(0)}° · 可見粒子 ${state.liquid.particles.length} · 已倒出 ${state.liquid.spilled}${stirLabel}`, 16, height - 18);
  }

  function drawActiveStage(time, dt) {
    if (activeStage === "plane") drawPlane(time, dt);
    else if (activeStage === "liquid") drawLiquid(time, dt);
  }

  function isExperimentAreaActive() {
    const root = $("module-experiments");
    return !!(root && root.classList.contains("active"));
  }

  function updateRunButton() {
    const button = $("experiment-pause-toggle");
    if (!button) return;
    button.setAttribute("aria-pressed", running ? "true" : "false");
    button.textContent = running ? "暫停模擬" : "開始模擬";
  }

  function setSimulationRunning(nextRunning, options = {}) {
    running = !!nextRunning;
    updateRunButton();
    if (!running) {
      stopLoop();
      if (options.drawPreview) drawActiveStage(performance.now(), 16);
      return;
    }
    drawActiveStage(performance.now(), 16);
    startLoop();
  }

  function frame(time) {
    if (!isExperimentAreaActive() || document.hidden || !running) {
      if (running) setSimulationRunning(false, { drawPreview: false });
      rafId = 0;
      return;
    }
    const dt = Math.min(64, lastFrameAt ? time - lastFrameAt : 16);
    lastFrameAt = time;
    drawActiveStage(time, dt);
    rafId = window.requestAnimationFrame(frame);
  }

  function startLoop() {
    if (rafId || !running || !isExperimentAreaActive() || document.hidden) return;
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

  function setActiveStage(stage, options = {}) {
    const nextStage = stage || "plane";
    const changed = nextStage !== activeStage;
    activeStage = nextStage;
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
    if (changed && !options.keepRunning) setSimulationRunning(false, { drawPreview: false });
    drawActiveStage(performance.now(), 16);
  }

  function bindControls() {
    document.querySelectorAll(".experiment-control input, .experiment-control select").forEach((input) => {
      syncControlValue(input);
      const redraw = () => {
        syncControlValue(input);
        if (input.id === "experiment-plane-view") applyPlaneViewPreset(input.value, true);
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
        setSimulationRunning(!running, { drawPreview: true });
      });
    }
    bindPlaneOrbitControls();
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
        state.liquid.particles.forEach((p) => {
          p.vx += randomRange(0.003, 0.011);
          p.vy += randomRange(-0.004, 0.003);
        });
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
    window.addEventListener("resize", () => {
      resizeCanvases();
      if (isExperimentAreaActive()) drawActiveStage(performance.now(), 16);
    }, { passive: true });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) setSimulationRunning(false, { drawPreview: false });
      else if (isExperimentAreaActive()) drawActiveStage(performance.now(), 16);
    });
  }

  function initExperimentArea() {
    const root = $("module-experiments");
    if (!root) return;
    if (!state.plane.particles.length) seedPlaneParticles();
    if (!state.liquid.particles.length) seedLiquidParticles();
    if (!initialized) {
      initialized = true;
      bindControls();
    }
    resizeCanvases();
    setActiveStage(activeStage, { keepRunning: true });
    if (!running) stopLoop();
    updateRunButton();
  }

  window.initExperimentArea = initExperimentArea;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initExperimentArea, { once: true });
  } else {
    initExperimentArea();
  }
})();
