'use strict';

(function () {
  const helpers = window.HACKME_LOCAL_GAME_HELPERS || {};
  const clamp = helpers.clamp || ((value, min, max) => Math.max(min, Math.min(max, value)));
  const WORLD_SIZE = 168;
  const ROAD_WIDTH = 9;
  const PLAYER_RADIUS = 1.05;
  const VEHICLE_RADIUS = 2.1;
  const OPEN_WORLD_ROADS = [-72, -48, -24, 0, 24, 48, 72];
  const OPEN_WORLD_BLOCK_CENTERS = [-60, -36, -12, 12, 36, 60];
  const ENTER_VEHICLE_DISTANCE = 6.5;
  const TRAFFIC_HIT_DISTANCE = 9.5;
  const PATROL_DAMAGE_DISTANCE = 14;
  const PICKUP_DISTANCE = 3;
  const TAIL_GADGET_HIT_DISTANCE = 3;
  const PATROL_GADGET_HIT_DISTANCE = 3;
  const OPEN_WORLD_VEHICLE_SPAWNS = [
    { x: -63, z: -48, angle: Math.PI / 2, type: "sedan", color: "#ef4444", maxSpeed: 31, accel: 26, handling: 1.85 },
    { x: -24, z: 66, angle: 0, type: "van", color: "#f97316", maxSpeed: 24, accel: 18, handling: 1.35 },
    { x: 42, z: -24, angle: -Math.PI / 2, type: "coupe", color: "#22c55e", maxSpeed: 36, accel: 30, handling: 2.05 },
    { x: 72, z: 24, angle: Math.PI, type: "sports", color: "#a855f7", maxSpeed: 42, accel: 34, handling: 2.25 },
    { x: -48, z: 0, angle: Math.PI / 2, type: "taxi", color: "#facc15", maxSpeed: 30, accel: 25, handling: 1.75 },
  ];
  const OPEN_WORLD_PICKUP_SPAWNS = [
    { type: "health", x: 54, z: 54, color: "#ef4444", label: "醫藥箱" },
    { type: "armor", x: -66, z: 66, color: "#38bdf8", label: "防具" },
    { type: "fuel", x: 72, z: -48, color: "#facc15", label: "燃料" },
    { type: "ammo", x: -36, z: -72, color: "#a78bfa", label: "干擾器" },
  ];
  const OPEN_WORLD_MISSIONS = [
    {
      key: "courier",
      label: "快遞路線",
      district: "舊港碼頭",
      reward: 900,
      timeLimit: 150,
      color: "#38bdf8",
      start: { x: -69, z: 54 },
      target: { x: 66, z: -58 },
    },
    {
      key: "race",
      label: "環城競速",
      district: "中央環線",
      reward: 1180,
      timeLimit: 135,
      color: "#f59e0b",
      gates: [
        { x: -70, z: -70 },
        { x: 4, z: -72 },
        { x: 73, z: -46 },
        { x: 70, z: 38 },
        { x: 10, z: 72 },
        { x: -70, z: 58 },
      ],
    },
    {
      key: "rescue",
      label: "城市救援",
      district: "醫療區",
      reward: 980,
      timeLimit: 145,
      color: "#22c55e",
      start: { x: 57, z: 67 },
      target: { x: -56, z: -66 },
    },
    {
      key: "tail",
      label: "追蹤干擾車",
      district: "工業外環",
      reward: 1260,
      timeLimit: 160,
      color: "#ef4444",
      target: { x: 69, z: 5 },
    },
  ];

  function openWorldRandom(state) {
    return typeof state?.rng === "function" ? state.rng() : Math.random();
  }

  function distance2(x1, z1, x2, z2) {
    const dx = x1 - x2;
    const dz = z1 - z2;
    return dx * dx + dz * dz;
  }

  function distance(x1, z1, x2, z2) {
    return Math.sqrt(distance2(x1, z1, x2, z2));
  }

  function withinDistance2(x1, z1, x2, z2, radius) {
    return distance2(x1, z1, x2, z2) <= radius * radius;
  }

  function angleTo(fromX, fromZ, toX, toZ) {
    return Math.atan2(toX - fromX, toZ - fromZ);
  }

  function normalizeAngle(angle) {
    let next = angle;
    while (next > Math.PI) next -= Math.PI * 2;
    while (next < -Math.PI) next += Math.PI * 2;
    return next;
  }

  function colorFromHex(THREE, value) {
    return new THREE.Color(value || "#ffffff");
  }

  function makeMaterial(THREE, color, roughness = 0.78, metalness = 0.05) {
    return new THREE.MeshStandardMaterial({
      color: colorFromHex(THREE, color),
      roughness,
      metalness,
    });
  }

  function createBox(THREE, width, height, depth, color) {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(width, height, depth),
      makeMaterial(THREE, color),
    );
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  }

  function createCylinder(THREE, radius, height, color, segments = 18) {
    const mesh = new THREE.Mesh(
      new THREE.CylinderGeometry(radius, radius, height, segments),
      makeMaterial(THREE, color),
    );
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  }

  function createCityCarMesh(THREE, color = "#ef4444", options = {}) {
    const group = new THREE.Group();
    const body = createBox(THREE, options.length || 4.2, 0.9, options.width || 2.25, color);
    body.position.y = 0.72;
    const cabin = createBox(THREE, 1.72, 0.76, 1.72, options.cabin || "#dbeafe");
    cabin.position.set(-0.1, 1.34, -0.08);
    cabin.material.transparent = true;
    cabin.material.opacity = 0.72;
    const front = createBox(THREE, 0.16, 0.28, 1.25, "#fef3c7");
    front.position.set(2.14, 0.83, 0);
    const rear = createBox(THREE, 0.14, 0.24, 1.14, "#fb7185");
    rear.position.set(-2.12, 0.82, 0);
    const wheelMat = makeMaterial(THREE, "#111827", 0.92, 0.16);
    [-1.45, 1.45].forEach((x) => {
      [-1.18, 1.18].forEach((z) => {
        const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.34, 0.34, 0.3, 14), wheelMat);
        wheel.rotation.x = Math.PI / 2;
        wheel.position.set(x, 0.32, z);
        wheel.castShadow = true;
        group.add(wheel);
      });
    });
    group.add(body, cabin, front, rear);
    if (options.lightbar) {
      const bar = createBox(THREE, 0.95, 0.16, 0.28, "#e0f2fe");
      bar.position.set(0, 1.82, 0);
      const red = createBox(THREE, 0.34, 0.18, 0.32, "#ef4444");
      red.position.set(-0.24, 1.92, 0);
      const blue = createBox(THREE, 0.34, 0.18, 0.32, "#2563eb");
      blue.position.set(0.24, 1.92, 0);
      group.add(bar, red, blue);
    }
    return group;
  }

  function createPlayerMesh(THREE) {
    const group = new THREE.Group();
    const legs = createCylinder(THREE, 0.36, 0.95, "#1f2937", 14);
    legs.position.y = 0.48;
    const torso = createCylinder(THREE, 0.48, 0.98, "#2563eb", 16);
    torso.position.y = 1.32;
    const head = new THREE.Mesh(
      new THREE.SphereGeometry(0.36, 18, 12),
      makeMaterial(THREE, "#f8d0a8"),
    );
    head.position.y = 2.05;
    const visor = createBox(THREE, 0.36, 0.08, 0.09, "#0f172a");
    visor.position.set(0, 2.08, 0.33);
    group.add(legs, torso, head, visor);
    return group;
  }

  function createMissionMarker(THREE) {
    const group = new THREE.Group();
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(2.35, 0.16, 10, 34),
      new THREE.MeshStandardMaterial({
        color: 0x38bdf8,
        emissive: 0x0ea5e9,
        emissiveIntensity: 0.4,
        roughness: 0.48,
      }),
    );
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 0.16;
    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(0.38, 0.38, 5.8, 18, 1, true),
      new THREE.MeshStandardMaterial({
        color: 0x38bdf8,
        emissive: 0x0ea5e9,
        emissiveIntensity: 0.18,
        transparent: true,
        opacity: 0.28,
      }),
    );
    beam.position.y = 2.9;
    group.add(ring, beam);
    group.userData.ring = ring;
    group.userData.beam = beam;
    return group;
  }

  function createGadgetProjectileMesh(THREE) {
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(0.22, 12, 8),
      new THREE.MeshStandardMaterial({
        color: 0xa78bfa,
        emissive: 0x7c3aed,
        emissiveIntensity: 0.8,
        roughness: 0.42,
      }),
    );
    mesh.castShadow = true;
    return mesh;
  }

  function disposeOpenWorldObject(object) {
    object?.geometry?.dispose?.();
    const materials = Array.isArray(object?.material)
      ? object.material
      : object?.material
        ? [object.material]
        : [];
    materials.forEach((material) => material.dispose?.());
    object?.removeFromParent?.();
  }

  function setObjectPose(object, x, z, angle = 0, y = 0) {
    object.position.set(x, y, z);
    object.rotation.y = angle;
  }

  function isOnRoad(value) {
    return OPEN_WORLD_ROADS.some((road) => Math.abs(value - road) <= ROAD_WIDTH * 0.56);
  }

  function circleHitsRect(x, z, radius, rect) {
    const halfW = rect.w / 2;
    const halfD = rect.d / 2;
    const closestX = clamp(x, rect.x - halfW, rect.x + halfW);
    const closestZ = clamp(z, rect.z - halfD, rect.z + halfD);
    return distance2(x, z, closestX, closestZ) < radius * radius;
  }

  function openWorldReservedPoints() {
    const missionPoints = OPEN_WORLD_MISSIONS.flatMap((mission) => {
      if (mission.gates) return mission.gates;
      return [mission.start, mission.target].filter(Boolean);
    });
    return [
      { x: 0, z: 6, radius: 7 },
      ...missionPoints.map((point) => ({ x: point.x, z: point.z, radius: 7 })),
      ...OPEN_WORLD_VEHICLE_SPAWNS.map((point) => ({ x: point.x, z: point.z, radius: 6 })),
      ...OPEN_WORLD_PICKUP_SPAWNS.map((point) => ({ x: point.x, z: point.z, radius: 5 })),
    ];
  }

  function blocksReservedPoint(x, z, w, d) {
    return openWorldReservedPoints().some((point) => (
      circleHitsRect(point.x, point.z, point.radius, { x, z, w, d })
    ));
  }

  function openWorldBlocked(state, x, z, radius) {
    const edge = WORLD_SIZE / 2 - radius - 1.2;
    if (x < -edge || x > edge || z < -edge || z > edge) return true;
    return state.colliders.some((rect) => circleHitsRect(x, z, radius + 0.2, rect));
  }

  function addOpenWorldHeat(state, amount, reason = "") {
    state.heat = clamp(Number(state.heat || 0) + Number(amount || 0), 0, 100);
    state.lastHeatReason = reason || state.lastHeatReason || "";
    state.lastHeatAt = performance.now();
  }

  function formatOpenWorldTime(ms) {
    const total = Math.max(0, Math.ceil(Number(ms || 0) / 1000));
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function activeMission(state) {
    return OPEN_WORLD_MISSIONS[state.missionIndex % OPEN_WORLD_MISSIONS.length] || OPEN_WORLD_MISSIONS[0];
  }

  function currentMissionTarget(state) {
    const mission = activeMission(state);
    const missionState = state.missionState || {};
    if (mission.key === "race") {
      return mission.gates?.[missionState.gateIndex || 0] || mission.gates?.[0] || { x: 0, z: 0 };
    }
    if (mission.key === "tail") return missionState.target || mission.target || { x: 0, z: 0 };
    if (missionState.stage === "dropoff") return mission.target || { x: 0, z: 0 };
    return mission.start || mission.target || { x: 0, z: 0 };
  }

  function chooseTailWaypoint(state) {
    const roadX = OPEN_WORLD_ROADS[Math.floor(openWorldRandom(state) * OPEN_WORLD_ROADS.length)] || 0;
    const roadZ = OPEN_WORLD_ROADS[Math.floor(openWorldRandom(state) * OPEN_WORLD_ROADS.length)] || 0;
    return {
      x: clamp(roadX + (openWorldRandom(state) - 0.5) * 6, -76, 76),
      z: clamp(roadZ + (openWorldRandom(state) - 0.5) * 6, -76, 76),
    };
  }

  function updateMissionMarker(state) {
    if (!state.missionMarker) return;
    const mission = activeMission(state);
    const target = currentMissionTarget(state);
    setObjectPose(state.missionMarker, target.x, target.z, 0, 0.08);
    const color = colorFromHex(state.THREE, mission.color);
    state.missionMarker.userData.ring.material.color.copy(color);
    state.missionMarker.userData.ring.material.emissive.copy(color);
    state.missionMarker.userData.beam.material.color.copy(color);
    state.missionMarker.userData.beam.material.emissive.copy(color);
  }

  function prepareOpenWorldMission(state) {
    const mission = activeMission(state);
    state.missionState = {
      stage: mission.key === "race" ? "race" : mission.key === "tail" ? "tail" : "pickup",
      gateIndex: 0,
      tailSeconds: 0,
      tailWaypoint: null,
      startedAt: Date.now(),
      expiresAt: Date.now() + Number(mission.timeLimit || 150) * 1000,
      target: mission.target ? { ...mission.target } : null,
    };
    if (mission.key === "tail") {
      if (!state.tailTarget) {
        const mesh = createCityCarMesh(state.THREE, "#7f1d1d", { cabin: "#fecaca", length: 4.7, width: 2.35 });
        state.scene.add(mesh);
        state.tailTarget = {
          x: mission.target.x,
          z: mission.target.z,
          angle: -Math.PI / 2,
          speed: 13,
          mesh,
        };
      }
      state.tailTarget.x = mission.target.x;
      state.tailTarget.z = mission.target.z;
      state.tailTarget.angle = -Math.PI / 2;
      state.tailTarget.mesh.visible = true;
      state.missionState.target = { x: state.tailTarget.x, z: state.tailTarget.z };
      state.missionState.tailWaypoint = chooseTailWaypoint(state);
    } else if (state.tailTarget) {
      state.tailTarget.mesh.visible = false;
    }
    updateMissionMarker(state);
  }

  function openWorldMissionProgressText(state) {
    const mission = activeMission(state);
    const missionState = state.missionState || {};
    if (mission.key === "courier") return missionState.stage === "dropoff" ? "送往目的地" : "領取包裹";
    if (mission.key === "rescue") return missionState.stage === "dropoff" ? "送往醫療區" : "接應求助者";
    if (mission.key === "race") return `檢查點 ${(missionState.gateIndex || 0) + 1}/${mission.gates.length}`;
    if (mission.key === "tail") return `保持跟車 ${Math.floor(missionState.tailSeconds || 0)}/10 秒`;
    return "探索城市";
  }

  function completeOpenWorldMission(api, state) {
    const mission = activeMission(state);
    const remaining = Math.max(0, Number(state.missionState?.expiresAt || Date.now()) - Date.now());
    const timeBonus = Math.round(remaining / 100);
    const heatBonus = state.heat < 20 ? 180 : state.heat < 45 ? 80 : 0;
    state.score += mission.reward + timeBonus + heatBonus;
    state.cash += Math.round((mission.reward + timeBonus) / 12);
    state.missionsCompleted += 1;
    state.combo += 1;
    state.missionFinishedAt = Date.now();
    api.achievement?.(`mission-${mission.key}`, `${mission.label}完成`, `完成 ${mission.district} 的開放世界任務。`);
    if (state.missionsCompleted >= 3) api.achievement?.("city-runner", "城市跑者", "同一局完成三個城市任務。");
    if (state.heat >= 60) api.achievement?.("high-heat-clear", "高警戒收工", "在高警戒狀態完成任務。");
    state.missionIndex = (state.missionIndex + 1) % OPEN_WORLD_MISSIONS.length;
    prepareOpenWorldMission(state);
    api.status(`任務完成：${mission.label} · 分數 ${Number(state.score).toLocaleString()}`);
  }

  function cycleOpenWorldMission(api, state) {
    if (!state) return;
    if (state.status === "active") {
      state.score = Math.max(0, state.score - 120);
      addOpenWorldHeat(state, 5, "任務臨時改派");
    }
    state.missionIndex = (state.missionIndex + 1) % OPEN_WORLD_MISSIONS.length;
    prepareOpenWorldMission(state);
    api.status(`已切換任務：${activeMission(state).label}`);
  }

  function buildOpenWorldCity(api, state) {
    const THREE = state.THREE;
    const stage = state.stage;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x8ec5d6);
    scene.fog = new THREE.Fog(0x8ec5d6, 78, 210);
    const camera = new THREE.PerspectiveCamera(58, 16 / 9, 0.1, 420);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.shadowMap.enabled = true;
    renderer.domElement.className = "open-world-canvas";
    stage.appendChild(renderer.domElement);
    state.scene = scene;
    state.camera = camera;
    state.renderer = renderer;

    const hemi = new THREE.HemisphereLight(0xf8fafc, 0x475569, 1.25);
    scene.add(hemi);
    const sun = new THREE.DirectionalLight(0xffffff, 1.8);
    sun.position.set(42, 90, 30);
    sun.castShadow = true;
    sun.shadow.camera.near = 1;
    sun.shadow.camera.far = 220;
    sun.shadow.camera.left = -95;
    sun.shadow.camera.right = 95;
    sun.shadow.camera.top = 95;
    sun.shadow.camera.bottom = -95;
    scene.add(sun);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(WORLD_SIZE + 18, WORLD_SIZE + 18),
      makeMaterial(THREE, "#6aa37a", 0.88, 0),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    const roadMaterial = makeMaterial(THREE, "#2f3542", 0.92, 0);
    const lineMaterial = makeMaterial(THREE, "#f8fafc", 0.55, 0);
    OPEN_WORLD_ROADS.forEach((x) => {
      const road = new THREE.Mesh(new THREE.PlaneGeometry(ROAD_WIDTH, WORLD_SIZE + 8), roadMaterial);
      road.rotation.x = -Math.PI / 2;
      road.position.set(x, 0.025, 0);
      road.receiveShadow = true;
      scene.add(road);
      const line = new THREE.Mesh(new THREE.PlaneGeometry(0.32, WORLD_SIZE), lineMaterial);
      line.rotation.x = -Math.PI / 2;
      line.position.set(x, 0.04, 0);
      scene.add(line);
    });
    OPEN_WORLD_ROADS.forEach((z) => {
      const road = new THREE.Mesh(new THREE.PlaneGeometry(WORLD_SIZE + 8, ROAD_WIDTH), roadMaterial);
      road.rotation.x = -Math.PI / 2;
      road.position.set(0, 0.03, z);
      road.receiveShadow = true;
      scene.add(road);
      const line = new THREE.Mesh(new THREE.PlaneGeometry(WORLD_SIZE, 0.32), lineMaterial);
      line.rotation.x = -Math.PI / 2;
      line.position.set(0, 0.045, z);
      scene.add(line);
    });

    const plazas = [
      { x: 0, z: 0, w: 18, d: 18, color: "#94a3b8" },
      { x: 54, z: 54, w: 24, d: 18, color: "#4ade80" },
      { x: -58, z: -62, w: 24, d: 18, color: "#7dd3fc" },
    ];
    plazas.forEach((plaza) => {
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(plaza.w, plaza.d), makeMaterial(THREE, plaza.color, 0.8, 0));
      mesh.rotation.x = -Math.PI / 2;
      mesh.position.set(plaza.x, 0.06, plaza.z);
      mesh.receiveShadow = true;
      scene.add(mesh);
    });

    const buildingColors = ["#b45309", "#475569", "#9ca3af", "#facc15", "#64748b", "#c084fc"];
    OPEN_WORLD_BLOCK_CENTERS.forEach((x) => {
      OPEN_WORLD_BLOCK_CENTERS.forEach((z) => {
        if (Math.abs(x) < 16 && Math.abs(z) < 16) return;
        if (x > 42 && z > 42) return;
        if (x < -46 && z < -48) return;
        const h = 4.5 + ((Math.abs(x * 13 + z * 7) % 10) * 1.15);
        const w = 7 + (Math.abs(x + z) % 3);
        const d = 7 + (Math.abs(x - z) % 4);
        const collider = { x, z, w: w + 1.2, d: d + 1.2 };
        if (blocksReservedPoint(collider.x, collider.z, collider.w, collider.d)) return;
        const color = buildingColors[Math.abs(Math.floor((x + 91) * 3 + z)) % buildingColors.length];
        const building = createBox(THREE, w, h, d, color);
        building.position.set(x, h / 2, z);
        scene.add(building);
        state.colliders.push(collider);
        if ((Math.abs(x + z) % 4) === 0) {
          const roof = createBox(THREE, w * 0.7, 0.35, d * 0.7, "#111827");
          roof.position.set(x, h + 0.22, z);
          scene.add(roof);
        }
      });
    });

    const landmarkTower = createBox(THREE, 7, 24, 7, "#0f766e");
    landmarkTower.position.set(-18, 12, 18);
    scene.add(landmarkTower);
    state.colliders.push({ x: -18, z: 18, w: 9, d: 9 });

    const playerMesh = createPlayerMesh(THREE);
    scene.add(playerMesh);
    state.player.mesh = playerMesh;

    state.vehicles = OPEN_WORLD_VEHICLE_SPAWNS.map((vehicle) => {
      const mesh = createCityCarMesh(THREE, vehicle.color, { cabin: vehicle.type === "taxi" ? "#fef9c3" : "#dbeafe" });
      setObjectPose(mesh, vehicle.x, vehicle.z, vehicle.angle);
      scene.add(mesh);
      return { ...vehicle, mesh, speed: 0, occupied: false };
    });

    state.traffic = [];
    for (let i = 0; i < 16; i += 1) {
      const axis = i % 2 ? "x" : "z";
      const road = OPEN_WORLD_ROADS[(i * 3) % OPEN_WORLD_ROADS.length];
      const lane = (i % 4 < 2 ? -1 : 1) * 1.85;
      const mesh = createCityCarMesh(THREE, i % 3 ? "#0ea5e9" : "#f43f5e", { cabin: "#e0f2fe" });
      const row = {
        axis,
        road,
        lane,
        dir: i % 4 < 2 ? 1 : -1,
        speed: 8.5 + (i % 5) * 1.2,
        x: axis === "x" ? -76 + ((i * 19) % 152) : road + lane,
        z: axis === "z" ? -76 + ((i * 23) % 152) : road + lane,
        mesh,
      };
      setObjectPose(mesh, row.x, row.z, axis === "x" ? Math.PI / 2 * row.dir : row.dir > 0 ? 0 : Math.PI);
      scene.add(mesh);
      state.traffic.push(row);
    }

    state.patrols = [];
    for (let i = 0; i < 4; i += 1) {
      const mesh = createCityCarMesh(THREE, "#f8fafc", { cabin: "#bfdbfe", lightbar: true, length: 4.6 });
      const patrol = {
        x: [-72, 72, -72, 72][i],
        z: [-72, -72, 72, 72][i],
        angle: i < 2 ? 0 : Math.PI,
        speed: 0,
        mesh,
        stunnedUntil: 0,
      };
      setObjectPose(mesh, patrol.x, patrol.z, patrol.angle);
      scene.add(mesh);
      state.patrols.push(patrol);
    }

    state.pickups = OPEN_WORLD_PICKUP_SPAWNS.map((pickup) => {
      const mesh = createCylinder(THREE, 0.9, 0.35, pickup.color, 16);
      mesh.position.set(pickup.x, 0.35, pickup.z);
      scene.add(mesh);
      return { ...pickup, mesh, active: true, spin: openWorldRandom(state) * Math.PI * 2 };
    });

    state.missionMarker = createMissionMarker(THREE);
    scene.add(state.missionMarker);
    prepareOpenWorldMission(state);

    resizeOpenWorldRenderer(state);
    updateOpenWorldCamera(state);
    renderer.render(scene, camera);
  }

  function resizeOpenWorldRenderer(state) {
    if (!state?.renderer || !state?.stage || !state?.camera) return;
    const rect = state.stage.getBoundingClientRect();
    const width = Math.max(320, Math.floor(rect.width || 760));
    const height = Math.max(240, Math.floor(rect.height || width * 0.56));
    state.renderer.setSize(width, height, false);
    state.camera.aspect = width / height;
    state.camera.updateProjectionMatrix();
  }

  function updateOpenWorldCamera(state) {
    const player = state.player;
    const speedRatio = Math.min(1, Math.abs(player.speed || 0) / 35);
    const chase = player.inVehicle ? 16 + speedRatio * 7 : 11;
    const height = player.inVehicle ? 8.2 + speedRatio * 1.6 : 6.2;
    const lookY = player.inVehicle ? 1.2 : 1.6;
    const cameraX = player.x - Math.sin(player.angle) * chase;
    const cameraZ = player.z - Math.cos(player.angle) * chase;
    if (!state.cameraReady) {
      state.camera.position.set(cameraX, height, cameraZ);
      state.cameraReady = true;
    } else {
      state.camera.position.lerp(new state.THREE.Vector3(cameraX, height, cameraZ), 0.18);
    }
    state.camera.lookAt(player.x, lookY, player.z);
  }

  function setOpenWorldInput(state, name, pressed) {
    if (!state) return;
    state.keys[name] = Boolean(pressed);
  }

  function nearestOpenWorldVehicle(state) {
    if (state.player.inVehicle) return state.player.inVehicle;
    let best = null;
    let bestD = Infinity;
    state.vehicles.forEach((vehicle) => {
      if (vehicle.occupied) return;
      const d = distance2(state.player.x, state.player.z, vehicle.x, vehicle.z);
      if (d < bestD) {
        bestD = d;
        best = vehicle;
      }
    });
    return bestD <= ENTER_VEHICLE_DISTANCE * ENTER_VEHICLE_DISTANCE ? best : null;
  }

  function toggleOpenWorldVehicle(api, state) {
    if (!state || state.status !== "active") {
      api.status("開始後才能上車。");
      return;
    }
    const player = state.player;
    if (player.inVehicle) {
      const vehicle = player.inVehicle;
      const exitX = vehicle.x - Math.cos(vehicle.angle) * 2.7;
      const exitZ = vehicle.z + Math.sin(vehicle.angle) * 2.7;
      if (openWorldBlocked(state, exitX, exitZ, PLAYER_RADIUS)) {
        api.status("旁邊沒有安全下車空間。");
        return;
      }
      vehicle.occupied = false;
      vehicle.speed = player.speed * 0.2;
      player.inVehicle = null;
      player.x = exitX;
      player.z = exitZ;
      player.speed = 0;
      player.mesh.visible = true;
      setObjectPose(player.mesh, player.x, player.z, player.angle);
      api.achievement?.("first-exit", "街頭切換", "完成一次上下車切換。");
      return;
    }
    const vehicle = nearestOpenWorldVehicle(state);
    if (!vehicle) {
      api.status("附近沒有可駕駛車輛。");
      return;
    }
    vehicle.occupied = true;
    player.inVehicle = vehicle;
    player.x = vehicle.x;
    player.z = vehicle.z;
    player.angle = vehicle.angle;
    player.speed = vehicle.speed || 0;
    player.mesh.visible = false;
    api.achievement?.("first-drive", "城市駕駛", "第一次進入車輛。");
  }

  function fireOpenWorldGadget(api, state) {
    if (!state || state.status !== "active" || state.gadgetAmmo <= 0 || state.fireCooldown > 0) return;
    state.gadgetAmmo -= 1;
    state.fireCooldown = 0.42;
    const mesh = createGadgetProjectileMesh(state.THREE);
    state.scene.add(mesh);
    state.projectiles.push({
      x: state.player.x + Math.sin(state.player.angle) * 2,
      z: state.player.z + Math.cos(state.player.angle) * 2,
      angle: state.player.angle,
      life: 0.9,
      speed: 42,
      mesh,
    });
    addOpenWorldHeat(state, 3, "市區使用干擾器");
    if (api.status) api.status("干擾器已發射。");
  }

  function updateOpenWorldMovement(state, dt) {
    const player = state.player;
    const turn = (state.keys.left ? 1 : 0) - (state.keys.right ? 1 : 0);
    const throttle = (state.keys.up ? 1 : 0) - (state.keys.down ? 1 : 0);
    const sprint = Boolean(state.keys.sprint);
    if (player.inVehicle) {
      const vehicle = player.inVehicle;
      const maxSpeed = vehicle.maxSpeed || 30;
      const accel = vehicle.accel || 22;
      const handling = vehicle.handling || 1.7;
      player.speed += throttle * accel * dt;
      if (!throttle) player.speed *= Math.pow(0.12, dt);
      if (sprint && throttle > 0) {
        player.speed += accel * 0.55 * dt;
        state.fuel = clamp(state.fuel - dt * 3.2, 0, 100);
      }
      if (state.fuel <= 0 && player.speed > maxSpeed * 0.5) player.speed = maxSpeed * 0.5;
      player.speed = clamp(player.speed, -maxSpeed * 0.48, maxSpeed * (sprint && state.fuel > 0 ? 1.18 : 1));
      const turnScale = (Math.abs(player.speed) / maxSpeed) * 0.72 + 0.18;
      player.angle += turn * handling * turnScale * dt * (player.speed < -0.4 ? -1 : 1);
      const nextX = player.x + Math.sin(player.angle) * player.speed * dt;
      const nextZ = player.z + Math.cos(player.angle) * player.speed * dt;
      if (openWorldBlocked(state, nextX, nextZ, VEHICLE_RADIUS)) {
        player.speed *= -0.24;
        state.health = clamp(state.health - 5, 0, 100);
        addOpenWorldHeat(state, 7, "碰撞事故");
        state.score = Math.max(0, state.score - 45);
      } else {
        player.x = nextX;
        player.z = nextZ;
        state.distanceDriven += Math.abs(player.speed) * dt;
      }
      vehicle.x = player.x;
      vehicle.z = player.z;
      vehicle.angle = player.angle;
      vehicle.speed = player.speed;
      setObjectPose(vehicle.mesh, vehicle.x, vehicle.z, vehicle.angle);
      return;
    }
    const walkSpeed = sprint ? 9.2 : 5.6;
    player.angle += turn * 2.4 * dt;
    player.speed = throttle * walkSpeed;
    const nextX = player.x + Math.sin(player.angle) * player.speed * dt;
    const nextZ = player.z + Math.cos(player.angle) * player.speed * dt;
    if (!openWorldBlocked(state, nextX, nextZ, PLAYER_RADIUS)) {
      player.x = nextX;
      player.z = nextZ;
      state.distanceWalked += Math.abs(player.speed) * dt;
    }
    setObjectPose(player.mesh, player.x, player.z, player.angle);
  }

  function updateOpenWorldTraffic(state, dt) {
    state.traffic.forEach((car) => {
      const delta = car.speed * car.dir * dt;
      if (car.axis === "x") {
        car.x += delta;
        if (car.x > 83) car.x = -83;
        if (car.x < -83) car.x = 83;
      } else {
        car.z += delta;
        if (car.z > 83) car.z = -83;
        if (car.z < -83) car.z = 83;
      }
      setObjectPose(car.mesh, car.x, car.z, car.axis === "x" ? Math.PI / 2 * car.dir : car.dir > 0 ? 0 : Math.PI);
      if (withinDistance2(car.x, car.z, state.player.x, state.player.z, TRAFFIC_HIT_DISTANCE)) {
        if (state.player.inVehicle && Math.abs(state.player.speed) > 9) {
          state.health = clamp(state.health - dt * 12, 0, 100);
          addOpenWorldHeat(state, dt * 8, "交通擦撞");
        }
      }
    });
  }

  function updateOpenWorldPatrols(state, dt) {
    const now = performance.now();
    state.patrols.forEach((patrol, index) => {
      const chasing = state.heat > 16 && now > Number(patrol.stunnedUntil || 0);
      let targetX = [-72, 72, -72, 72][index];
      let targetZ = [-72, -72, 72, 72][index];
      let desiredSpeed = 8;
      if (chasing) {
        targetX = state.player.x;
        targetZ = state.player.z;
        desiredSpeed = 14 + Math.min(12, state.heat * 0.13);
      }
      const desiredAngle = angleTo(patrol.x, patrol.z, targetX, targetZ);
      patrol.angle = normalizeAngle(patrol.angle + clamp(normalizeAngle(desiredAngle - patrol.angle), -2.4 * dt, 2.4 * dt));
      patrol.speed += (desiredSpeed - patrol.speed) * Math.min(1, dt * 1.8);
      const nextX = patrol.x + Math.sin(patrol.angle) * patrol.speed * dt;
      const nextZ = patrol.z + Math.cos(patrol.angle) * patrol.speed * dt;
      if (openWorldBlocked(state, nextX, nextZ, VEHICLE_RADIUS)) {
        patrol.angle += Math.PI * 0.35;
        patrol.speed *= 0.4;
      } else {
        patrol.x = nextX;
        patrol.z = nextZ;
      }
      setObjectPose(patrol.mesh, patrol.x, patrol.z, patrol.angle);
      if (chasing && withinDistance2(patrol.x, patrol.z, state.player.x, state.player.z, PATROL_DAMAGE_DISTANCE)) {
        state.health = clamp(state.health - dt * 7.5, 0, 100);
        state.heat = clamp(state.heat + dt * 2.8, 0, 100);
      }
    });
  }

  function updateOpenWorldPickups(state, dt) {
    state.pickups.forEach((pickup) => {
      if (!pickup.active) return;
      pickup.spin += dt * 2.6;
      pickup.mesh.rotation.y = pickup.spin;
      pickup.mesh.position.y = 0.4 + Math.sin(pickup.spin * 1.7) * 0.16;
      if (!withinDistance2(pickup.x, pickup.z, state.player.x, state.player.z, PICKUP_DISTANCE)) return;
      pickup.active = false;
      pickup.mesh.visible = false;
      state.powerupsCollected += 1;
      if (pickup.type === "health") state.health = clamp(state.health + 32, 0, 100);
      if (pickup.type === "armor") state.armor = clamp(state.armor + 45, 0, 100);
      if (pickup.type === "fuel") state.fuel = clamp(state.fuel + 42, 0, 100);
      if (pickup.type === "ammo") state.gadgetAmmo += 8;
      state.score += 110;
    });
  }

  function updateOpenWorldTailTarget(state, dt) {
    const target = state.tailTarget;
    if (!target?.mesh?.visible) return;
    if (!state.missionState) return;
    const playerDist = distance(target.x, target.z, state.player.x, state.player.z);
    let waypoint = state.missionState?.tailWaypoint;
    if (!waypoint || withinDistance2(target.x, target.z, waypoint.x, waypoint.z, 6)) {
      waypoint = chooseTailWaypoint(state);
      state.missionState.tailWaypoint = waypoint;
    }
    const evadeAngle = playerDist < 32
      ? angleTo(state.player.x, state.player.z, target.x, target.z)
      : angleTo(target.x, target.z, waypoint.x, waypoint.z);
    target.angle = normalizeAngle(target.angle + clamp(normalizeAngle(evadeAngle - target.angle), -1.7 * dt, 1.7 * dt));
    const nextX = target.x + Math.sin(target.angle) * target.speed * dt;
    const nextZ = target.z + Math.cos(target.angle) * target.speed * dt;
    if (openWorldBlocked(state, nextX, nextZ, VEHICLE_RADIUS)) {
      target.angle += Math.PI * 0.5;
    } else {
      target.x = clamp(nextX, -78, 78);
      target.z = clamp(nextZ, -78, 78);
    }
    setObjectPose(target.mesh, target.x, target.z, target.angle);
    if (state.missionState) state.missionState.target = { x: target.x, z: target.z };
  }

  function updateOpenWorldProjectiles(api, state, dt) {
    state.fireCooldown = Math.max(0, Number(state.fireCooldown || 0) - dt);
    state.projectiles.forEach((shot) => {
      shot.x += Math.sin(shot.angle) * shot.speed * dt;
      shot.z += Math.cos(shot.angle) * shot.speed * dt;
      shot.life -= dt;
      shot.mesh?.position.set(shot.x, 1.1, shot.z);
      const target = state.tailTarget;
      if (target?.mesh?.visible && withinDistance2(shot.x, shot.z, target.x, target.z, TAIL_GADGET_HIT_DISTANCE)) {
        shot.life = 0;
        state.gadgetHits += 1;
        state.score += 180;
        if (state.missionState) state.missionState.tailSeconds = Math.min(10, Number(state.missionState.tailSeconds || 0) + 2.6);
      }
      state.patrols.forEach((patrol) => {
        if (shot.life <= 0 || !withinDistance2(shot.x, shot.z, patrol.x, patrol.z, PATROL_GADGET_HIT_DISTANCE)) return;
        shot.life = 0;
        patrol.stunnedUntil = performance.now() + 2200;
        state.evades += 1;
        state.score += 90;
        state.heat = clamp(state.heat + 7, 0, 100);
      });
    });
    state.projectiles = state.projectiles.filter((shot) => {
      const alive = shot.life > 0 && Math.abs(shot.x) < 90 && Math.abs(shot.z) < 90;
      if (!alive) disposeOpenWorldObject(shot.mesh);
      return alive;
    });
  }

  function updateOpenWorldMission(api, state, dt) {
    const mission = activeMission(state);
    const missionState = state.missionState || {};
    if (!missionState.expiresAt) return;
    if (Date.now() > missionState.expiresAt) {
      state.score = Math.max(0, state.score - 160);
      prepareOpenWorldMission(state);
      api.status(`任務逾時，已重新安排：${activeMission(state).label}`);
      return;
    }
    const target = currentMissionTarget(state);
    const d = distance(state.player.x, state.player.z, target.x, target.z);
    if (mission.key === "race" && d < 5.2) {
      missionState.gateIndex += 1;
      state.score += 120 + missionState.gateIndex * 12;
      if (missionState.gateIndex >= mission.gates.length) completeOpenWorldMission(api, state);
      else updateMissionMarker(state);
      return;
    }
    if ((mission.key === "courier" || mission.key === "rescue") && d < 4.8) {
      if (missionState.stage !== "dropoff") {
        missionState.stage = "dropoff";
        state.score += 120;
        updateMissionMarker(state);
      } else {
        completeOpenWorldMission(api, state);
      }
      return;
    }
    if (mission.key === "tail") {
      const targetVehicle = state.tailTarget;
      if (targetVehicle?.mesh?.visible) {
        const followDist = distance(state.player.x, state.player.z, targetVehicle.x, targetVehicle.z);
        if (followDist < 18 && state.player.inVehicle) {
          missionState.tailSeconds += dt;
          state.score += dt * 18;
        } else if (followDist > 40) {
          missionState.tailSeconds = Math.max(0, missionState.tailSeconds - dt * 0.6);
        }
        if (missionState.tailSeconds >= 10) completeOpenWorldMission(api, state);
      }
      updateMissionMarker(state);
    }
  }

  function updateOpenWorldHeat(state, dt) {
    const player = state.player;
    if (player.inVehicle && Math.abs(player.speed) > 37 && !isOnRoad(player.x) && !isOnRoad(player.z)) {
      addOpenWorldHeat(state, dt * 7.5, "危險駕駛");
    }
    const nearPatrol = state.patrols.some((patrol) => withinDistance2(patrol.x, patrol.z, player.x, player.z, 24));
    if (!nearPatrol || state.heat < 18) state.heat = clamp(state.heat - dt * (nearPatrol ? 1.8 : 5.4), 0, 100);
    const oldStars = state.stars;
    state.stars = Math.min(5, Math.ceil(state.heat / 20));
    if (oldStars >= 3 && state.stars <= 1) state.evades += 1;
  }

  function updateOpenWorldHud(api, state) {
    if (!state.hud || !state.minimap) return;
    if (state.titleCard) state.titleCard.style.display = state.status === "ready" ? "" : "none";
    const mission = activeMission(state);
    const target = currentMissionTarget(state);
    const missionTime = Math.max(0, Number(state.missionState?.expiresAt || Date.now()) - Date.now());
    const mode = state.player.inVehicle ? `車輛 ${state.player.inVehicle.type}` : "步行";
    state.hud.innerHTML = `
      <div class="open-world-hud-row">
        <strong>${mission.label}</strong>
        <span>${openWorldMissionProgressText(state)}</span>
      </div>
      <div class="open-world-hud-grid">
        <span>分數 ${Math.round(state.score).toLocaleString()}</span>
        <span>現金 ${state.cash.toLocaleString()}</span>
        <span>生命 ${Math.round(state.health)}</span>
        <span>防具 ${Math.round(state.armor)}</span>
        <span>燃料 ${Math.round(state.fuel)}</span>
        <span>警戒 ${"★".repeat(state.stars) || "0"}</span>
        <span>${mode}</span>
        <span>${formatOpenWorldTime(missionTime)}</span>
      </div>
      <div class="open-world-hud-row open-world-hud-sub">
        <span>${mission.district}</span>
        <span>距離 ${Math.round(distance(state.player.x, state.player.z, target.x, target.z))}m · 干擾器 ${state.gadgetAmmo}</span>
      </div>
    `;
    drawOpenWorldMinimap(state);
    const now = performance.now();
    const statusText = `${mission.label} · ${openWorldMissionProgressText(state)} · ${mode} · 警戒 ${state.stars}`;
    if (
      state.status === "active" &&
      (statusText !== state.lastStatusText || now > Number(state.nextStatusAt || 0))
    ) {
      api.status(statusText);
      state.lastStatusText = statusText;
      state.nextStatusAt = now + 700;
    }
  }

  function drawOpenWorldMinimap(state) {
    const canvas = state.minimap;
    const ctx = canvas.getContext("2d");
    const size = canvas.width;
    ctx.clearRect(0, 0, size, size);
    ctx.fillStyle = "#102a1d";
    ctx.fillRect(0, 0, size, size);
    const scale = size / WORLD_SIZE;
    const toX = (x) => (x + WORLD_SIZE / 2) * scale;
    const toY = (z) => (z + WORLD_SIZE / 2) * scale;
    ctx.strokeStyle = "#64748b";
    ctx.lineWidth = Math.max(2, ROAD_WIDTH * scale);
    OPEN_WORLD_ROADS.forEach((road) => {
      ctx.beginPath();
      ctx.moveTo(toX(road), 0);
      ctx.lineTo(toX(road), size);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, toY(road));
      ctx.lineTo(size, toY(road));
      ctx.stroke();
    });
    ctx.fillStyle = "rgba(15,23,42,.6)";
    state.colliders.slice(0, 120).forEach((rect) => {
      ctx.fillRect(toX(rect.x - rect.w / 2), toY(rect.z - rect.d / 2), rect.w * scale, rect.d * scale);
    });
    const mission = activeMission(state);
    const target = currentMissionTarget(state);
    ctx.fillStyle = mission.color;
    ctx.beginPath();
    ctx.arc(toX(target.x), toY(target.z), 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#f8fafc";
    ctx.save();
    ctx.translate(toX(state.player.x), toY(state.player.z));
    ctx.rotate(state.player.angle);
    ctx.beginPath();
    ctx.moveTo(0, -7);
    ctx.lineTo(5, 6);
    ctx.lineTo(-5, 6);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  function renderOpenWorldFrame(state) {
    if (!state?.renderer) return;
    const t = performance.now() * 0.001;
    if (state.missionMarker) {
      state.missionMarker.rotation.y = t * 1.3;
      state.missionMarker.userData.beam.scale.y = 0.9 + Math.sin(t * 2.8) * 0.08;
    }
    state.renderer.render(state.scene, state.camera);
  }

  function disposeOpenWorldState(state) {
    if (!state) return;
    if (state.raf) cancelAnimationFrame(state.raf);
    state.raf = null;
    if (state.resizeHandler) window.removeEventListener("resize", state.resizeHandler);
    state.resizeHandler = null;
    state.projectiles?.forEach?.((shot) => disposeOpenWorldObject(shot.mesh));
    state.projectiles = [];
    state.scene?.traverse?.((object) => {
      object.geometry?.dispose?.();
      const materials = Array.isArray(object.material)
        ? object.material
        : object.material
          ? [object.material]
          : [];
      materials.forEach((material) => material.dispose?.());
    });
    state.renderer?.dispose?.();
    state.renderer?.forceContextLoss?.();
  }

  function tickOpenWorld(api, now) {
    const state = api._openWorldState;
    if (!state || state.status !== "active") return;
    const last = state.lastFrameAt || now;
    const dt = Math.min(0.05, Math.max(0.001, (now - last) / 1000));
    state.lastFrameAt = now;
    updateOpenWorldMovement(state, dt);
    updateOpenWorldTraffic(state, dt);
    updateOpenWorldTailTarget(state, dt);
    updateOpenWorldPatrols(state, dt);
    updateOpenWorldPickups(state, dt);
    updateOpenWorldProjectiles(api, state, dt);
    updateOpenWorldMission(api, state, dt);
    updateOpenWorldHeat(state, dt);
    if (state.armor > 0 && state.health < 100) {
      const repair = Math.min(state.armor, dt * 0.8);
      state.armor -= repair;
      state.health = clamp(state.health + repair * 0.45, 0, 100);
    }
    if (state.health <= 0) {
      finishOpenWorld(api, "城市行動失敗");
      return;
    }
    updateOpenWorldCamera(state);
    updateOpenWorldHud(api, state);
    renderOpenWorldFrame(state);
    state.raf = requestAnimationFrame((frameNow) => tickOpenWorld(api, frameNow));
  }

  function finishOpenWorld(api, reason = "結算") {
    const state = api._openWorldState;
    if (!state || state.status === "finished") return;
    if (state.status !== "active" || !state.startedAt) {
      api.status("尚未開始，按開始後才會計時與送出成績。");
      return;
    }
    state.status = "finished";
    state.completedAt = Date.now();
    if (state.raf) cancelAnimationFrame(state.raf);
    state.raf = null;
    updateOpenWorldHud(api, state);
    renderOpenWorldFrame(state);
    const score = Math.max(1, Math.round(state.score + state.missionsCompleted * 300 + state.evades * 90));
    api.status(`${reason} · 分數 ${score.toLocaleString()} · 任務 ${state.missionsCompleted}`);
    if (state.missionsCompleted > 0) api.achievement?.("score-posted", "城市紀錄", "完成一局 3D 都市開放世界。");
    if (state.evades > 0) api.achievement?.("clean-escape", "甩開追逐", "成功降低警戒並脫離追逐。");
    api.recordReplay?.({
      title: "都市開放世界",
      score,
      difficulty: "open-world-city",
      elapsed_ms: Math.max(1, state.completedAt - state.startedAt),
      summary: `任務 ${state.missionsCompleted} · 警戒 ${state.stars} · 駕駛 ${Math.round(state.distanceDriven)}m`,
      moves: [
        `missions=${state.missionsCompleted}`,
        `evades=${state.evades}`,
        `distance=${Math.round(state.distanceDriven + state.distanceWalked)}`,
      ],
    });
    api.submitScore?.({
      raw_elapsed_ms: Math.max(1, state.completedAt - state.startedAt),
      penalty_seconds: 0,
      elapsed_ms: Math.max(1, state.completedAt - state.startedAt),
      difficulty: "open-world-city",
      puzzle_id: state.dailyChallenge?.key || "open-world-city",
      score,
      guess_count: 0,
      missions: Number(state.missionsCompleted || 0),
      evasion: Number(state.evades || 0),
      drive: Math.round(state.distanceDriven || 0),
      powerup: Number(state.powerupsCollected || 0),
      weapon: Number(state.gadgetHits || 0),
      survive: state.health > 0 ? 1 : 0,
    });
  }

  function createOpenWorldState(api) {
    const THREE = window.THREE;
    const dailyChallenge = api.dailyChallenge?.() || null;
    const stage = api.root.querySelector(".open-world-stage");
    const state = {
      THREE,
      stage,
      titleCard: api.root.querySelector(".open-world-title-card"),
      hud: api.root.querySelector(".open-world-hud"),
      minimap: api.root.querySelector(".open-world-minimap"),
      status: "ready",
      startedAt: 0,
      completedAt: null,
      score: 0,
      cash: 0,
      health: 100,
      armor: 0,
      fuel: 100,
      heat: 0,
      stars: 0,
      combo: 0,
      evades: 0,
      missionsCompleted: 0,
      missionIndex: 0,
      missionState: null,
      missionFinishedAt: 0,
      gadgetAmmo: 8,
      gadgetHits: 0,
      fireCooldown: 0,
      powerupsCollected: 0,
      distanceDriven: 0,
      distanceWalked: 0,
      player: {
        x: 0,
        z: 6,
        angle: 0,
        speed: 0,
        mesh: null,
        inVehicle: null,
      },
      keys: {},
      colliders: [],
      vehicles: [],
      traffic: [],
      patrols: [],
      pickups: [],
      projectiles: [],
      tailTarget: null,
      dailyChallenge,
      rng: dailyChallenge?.seed ? window.createHackmeGameSeededRandom?.(dailyChallenge.seed) : null,
      raf: null,
      lastFrameAt: 0,
      lastStatusText: "",
      nextStatusAt: 0,
      cameraReady: false,
      resizeHandler: null,
    };
    buildOpenWorldCity(api, state);
    state.resizeHandler = () => {
      resizeOpenWorldRenderer(state);
      renderOpenWorldFrame(state);
    };
    window.addEventListener("resize", state.resizeHandler);
    return state;
  }

  function showOpenWorldReady(api) {
    disposeOpenWorldState(api._openWorldState);
    api._openWorldState = null;
    if (!window.THREE) {
      api.root.innerHTML = `<div class="game-page-empty"><strong>3D 引擎尚未載入</strong><span>需要 three.min.js 才能遊玩都市開放世界。</span></div>`;
      api.status("Three.js 尚未載入。");
      return;
    }
    api.root.innerHTML = `
      <div class="open-world-shell">
        <div class="open-world-stage" aria-label="都市開放世界遊戲畫面">
          <div class="open-world-title-card">
            <strong>都市開放世界</strong>
            <span>按開始後才會計時、產生警戒與送出成績</span>
          </div>
          <div class="open-world-hud" aria-live="polite"></div>
          <canvas class="open-world-minimap" width="168" height="168" aria-label="都市小地圖"></canvas>
        </div>
      </div>
    `;
    const state = createOpenWorldState(api);
    api._openWorldState = state;
    updateOpenWorldHud(api, state);
    renderOpenWorldFrame(state);
    api.status("待機 · 選擇任務後開始城市探索。");
  }

  function startOpenWorld(api) {
    if (!window.THREE) {
      showOpenWorldReady(api);
      return;
    }
    if (!api._openWorldState || api._openWorldState.status === "finished") showOpenWorldReady(api);
    const state = api._openWorldState || createOpenWorldState(api);
    api._openWorldState = state;
    state.status = "active";
    state.startedAt = Date.now();
    state.completedAt = null;
    state.score = 0;
    state.cash = 0;
    state.health = 100;
    state.armor = 0;
    state.fuel = 100;
    state.heat = 0;
    state.stars = 0;
    state.evades = 0;
    state.missionsCompleted = 0;
    state.distanceDriven = 0;
    state.distanceWalked = 0;
    state.gadgetAmmo = 8;
    state.gadgetHits = 0;
    state.powerupsCollected = 0;
    state.lastStatusText = "";
    state.nextStatusAt = 0;
    state.projectiles.forEach((shot) => disposeOpenWorldObject(shot.mesh));
    state.projectiles = [];
    state.player.x = 0;
    state.player.z = 6;
    state.player.angle = 0;
    state.player.speed = 0;
    if (state.player.inVehicle) {
      state.player.inVehicle.occupied = false;
      state.player.inVehicle = null;
    }
    state.player.mesh.visible = true;
    setObjectPose(state.player.mesh, state.player.x, state.player.z, state.player.angle);
    state.pickups.forEach((pickup) => {
      pickup.active = true;
      pickup.mesh.visible = true;
    });
    prepareOpenWorldMission(state);
    updateOpenWorldHud(api, state);
    if (state.raf) cancelAnimationFrame(state.raf);
    state.lastFrameAt = performance.now();
    state.raf = requestAnimationFrame((now) => tickOpenWorld(api, now));
    api.status(`${activeMission(state).label} 開始。`);
  }

  function handleOpenWorldKey(api, event, pressed) {
    const state = api._openWorldState;
    if (!state) return;
    const key = event.key;
    if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "a", "A", "d", "D", "w", "W", "s", "S", "Shift", " ", "e", "E", "m", "M"].includes(key)) {
      event.preventDefault?.();
    }
    if (key === "ArrowLeft" || key === "a" || key === "A") setOpenWorldInput(state, "left", pressed);
    if (key === "ArrowRight" || key === "d" || key === "D") setOpenWorldInput(state, "right", pressed);
    if (key === "ArrowUp" || key === "w" || key === "W") setOpenWorldInput(state, "up", pressed);
    if (key === "ArrowDown" || key === "s" || key === "S") setOpenWorldInput(state, "down", pressed);
    if (key === "Shift") setOpenWorldInput(state, "sprint", pressed);
    if ((key === "e" || key === "E") && pressed) toggleOpenWorldVehicle(api, state);
    if ((key === "m" || key === "M") && pressed) cycleOpenWorldMission(api, state);
    if (key === " " && pressed) fireOpenWorldGadget(api, state);
  }

  window.registerHackmeLocalGameModule("open_world", {
    mount(api) {
      api.setTitle("都市開放世界");
      api.setSwipeMode?.("hold");
      api.setActions(`
        <button class="btn game-mini-btn btn-primary" type="button" data-action="new">開始</button>
        <button class="btn game-mini-btn" type="button" data-action="mission">換任務</button>
        <button class="btn game-mini-btn" type="button" data-action="vehicle">上/下車</button>
        <button class="btn game-mini-btn" type="button" data-action="finish">結算</button>
      `);
      api.setControls(`
        <button class="btn game-mini-btn" type="button" data-hold="left">左</button>
        <button class="btn game-mini-btn" type="button" data-hold="up">前進</button>
        <button class="btn game-mini-btn" type="button" data-hold="down">後退</button>
        <button class="btn game-mini-btn" type="button" data-hold="right">右</button>
        <button class="btn game-mini-btn" type="button" data-hold="sprint">加速</button>
        <button class="btn game-mini-btn" type="button" data-open-world-control="vehicle">上車</button>
        <button class="btn game-mini-btn" type="button" data-open-world-control="gadget">干擾器</button>
        <button class="btn game-mini-btn" type="button" data-open-world-control="mission">任務</button>
      `);
      api.onAction = (action) => {
        const state = api._openWorldState;
        if (action === "new") startOpenWorld(api);
        if (action === "mission") cycleOpenWorldMission(api, state);
        if (action === "vehicle") toggleOpenWorldVehicle(api, state);
        if (action === "finish") finishOpenWorld(api, "手動結算");
      };
      api.onControl = (target, pressed) => {
        const state = api._openWorldState;
        if (!state) return;
        if (target.dataset.hold) setOpenWorldInput(state, target.dataset.hold, pressed);
        if (!pressed) return;
        if (target.dataset.openWorldControl === "vehicle") toggleOpenWorldVehicle(api, state);
        if (target.dataset.openWorldControl === "gadget") fireOpenWorldGadget(api, state);
        if (target.dataset.openWorldControl === "mission") cycleOpenWorldMission(api, state);
      };
      api.onKey = (event, pressed) => handleOpenWorldKey(api, event, pressed);
      showOpenWorldReady(api);
      return () => {
        disposeOpenWorldState(api._openWorldState);
        api._openWorldState = null;
      };
    },
  });
}());
