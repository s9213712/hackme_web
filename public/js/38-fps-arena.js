'use strict';

const FPS_ARENA_MODES = {
  aim: { label: "Aim Trainer", seconds: 60, health: 100 },
  pve: { label: "PvE Arena", seconds: 90, health: 100 },
  bomb: { label: "Bomb Defuse", seconds: 75, health: 100 },
  bot: { label: "Bot Match", seconds: 90, health: 100 },
};
const FPS_ARENA_WEAPONS = [
  { key: "rifle", label: "Rifle", mag: 30, reserve: 90, delay: 130, recoil: 0.012, damage: 1, spread: 0.002 },
  { key: "smg", label: "SMG", mag: 36, reserve: 144, delay: 82, recoil: 0.008, damage: 1, spread: 0.004 },
  { key: "marksman", label: "DMR", mag: 12, reserve: 48, delay: 260, recoil: 0.022, damage: 2, spread: 0.001 },
];

let fpsArenaState = null;
let fpsArenaRaf = null;
let fpsArenaResizeObserver = null;
let fpsArenaPointerDragging = false;
let fpsArenaLastPointer = null;
let fpsArenaTouchPointerId = null;
let fpsArenaTouchMoved = false;
let fpsArenaAudioContext = null;
const FPS_ARENA_SCOPE_SWAY = 0.0036;
const FPS_ARENA_BOT_FIRE_RANGE = 18;
const FPS_ARENA_PLAYER_RADIUS = 0.42;

function fpsArenaMode() {
  const selected = $("fps-arena-mode")?.value || "aim";
  return FPS_ARENA_MODES[selected] ? selected : "aim";
}

function fpsArenaModeLabel(mode) {
  return FPS_ARENA_MODES[mode]?.label || "Aim Trainer";
}

function isFpsArenaActive() {
  return fpsArenaState?.status === "active";
}

function fpsArenaFormatTime(ms) {
  return formatSoloGameTime(Math.max(0, ms || 0));
}

function fpsArenaScoreLine(state) {
  if (!state) return "選擇模式後開始，最高分列入排行榜。";
  const elapsed = Math.max(0, Date.now() - state.startedAt);
  const remaining = Math.max(0, state.durationMs - elapsed);
  return `${fpsArenaModeLabel(state.mode)} · 分數 ${Number(state.score || 0).toLocaleString()} · 命中 ${state.hits}/${state.shots} · 生命 ${Math.max(0, Math.ceil(state.health))} · ${fpsArenaFormatTime(remaining)}`;
}

function updateFpsArenaHud() {
  const hud = $("fps-arena-hud");
  if (!hud) return;
  if (!fpsArenaState) {
    hud.textContent = "尚未開始";
    return;
  }
  const state = fpsArenaState;
  const elapsed = Math.max(0, Date.now() - state.startedAt);
  const remaining = Math.max(0, state.durationMs - elapsed);
  const accuracy = state.shots > 0 ? Math.round((state.hits / state.shots) * 100) : 0;
  hud.innerHTML = [
    `<span>${sanitize(fpsArenaModeLabel(state.mode))}</span>`,
    `<span>分數 ${Number(state.score || 0).toLocaleString()}</span>`,
    `<span>命中率 ${accuracy}%</span>`,
    `<span>生命 ${Math.max(0, Math.ceil(state.health))}</span>`,
    `<span>${sanitize(state.weapon?.label || "Rifle")} ${state.ammo}/${state.reserve}${state.reloadingUntil > performance.now() ? " 換彈" : ""}</span>`,
    `<span>體力 ${Math.round(state.stamina ?? 100)}%</span>`,
    `<span>時間 ${fpsArenaFormatTime(remaining)}</span>`,
    state.mode === "bomb" ? `<span>拆彈 ${Math.min(100, Math.round(state.defuseProgress || 0))}%</span>` : "",
  ].join("");
}

function updateFpsArenaStatus(prefix = "") {
  const status = $("fps-arena-status");
  if (!status) return;
  if (!fpsArenaState) {
    status.textContent = "選擇模式後開始，最高分列入排行榜。";
    return;
  }
  const state = fpsArenaState;
  const line = fpsArenaScoreLine(state);
  status.textContent = state.status === "finished"
    ? `任務結束 · ${fpsArenaModeLabel(state.mode)} · 分數 ${Number(state.score || 0).toLocaleString()} · 命中 ${state.hits}/${state.shots}`
    : `${prefix ? `${prefix} ` : ""}${line}`;
  updateFpsArenaHud();
}

function disposeFpsArenaScene() {
  if (fpsArenaRaf) {
    cancelAnimationFrame(fpsArenaRaf);
    fpsArenaRaf = null;
  }
  if (fpsArenaResizeObserver) {
    fpsArenaResizeObserver.disconnect();
    fpsArenaResizeObserver = null;
  }
  if (fpsArenaState?.renderer) {
    fpsArenaState.renderer.dispose();
    const canvas = fpsArenaState.renderer.domElement;
    if (canvas?.parentNode) canvas.parentNode.removeChild(canvas);
  }
}

function fpsArenaMaterial(color, roughness = 0.78, metalness = 0.06) {
  return new THREE.MeshStandardMaterial({ color, roughness, metalness });
}

function fpsArenaAddBox(scene, x, y, z, sx, sy, sz, color) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), fpsArenaMaterial(color));
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  scene.add(mesh);
  return mesh;
}

function fpsArenaAddCylinder(scene, x, y, z, radius, height, color) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, height, 20), fpsArenaMaterial(color));
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  scene.add(mesh);
  return mesh;
}

function fpsArenaPickSpawnPoint(state) {
  const points = Array.isArray(state?.spawnPoints) ? state.spawnPoints : [];
  if (points.length) {
    const farPoints = points.filter((point) => !state.player || Math.hypot(point.x - state.player.x, point.z - state.player.z) > 7);
    const pool = farPoints.length ? farPoints : points;
    return pool[Math.floor(Math.random() * pool.length)];
  }
  return { x: Math.random() * 12 - 6, z: -7 - Math.random() * 16 };
}

function fpsArenaRegisterHumanPart(state, root, mesh, part, damage = 1, scoreBonus = 0) {
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.userData = {
    root,
    kind: root.userData.kind,
    part,
    damage,
    scoreBonus,
  };
  root.add(mesh);
  state.hittables.push(mesh);
  return mesh;
}

function fpsArenaAddTarget(state, kind, options = {}) {
  const torsoColor = kind === "bot" ? 0x38bdf8 : kind === "enemy" ? 0xf43f5e : 0x22c55e;
  const limbColor = kind === "bot" ? 0x0f5f9e : kind === "enemy" ? 0x7f1d1d : 0x166534;
  const headColor = kind === "bot" ? 0xbfdbfe : kind === "enemy" ? 0xfecaca : 0xdcfce7;
  const root = new THREE.Group();
  const spawn = options.x !== undefined || options.z !== undefined
    ? { x: options.x ?? (Math.random() * 12 - 6), z: options.z ?? (-7 - Math.random() * 16) }
    : fpsArenaPickSpawnPoint(state);
  root.position.set(spawn.x, options.y ?? 1.05, spawn.z);
  root.userData = {
    kind,
    hp: options.hp || (kind === "target" ? 1 : 2),
    score: options.score || (kind === "target" ? 120 : 180),
    speed: options.speed || 1,
    phase: Math.random() * Math.PI * 2,
    breathPhase: Math.random() * Math.PI * 2,
    baseY: root.position.y,
    lastAttack: 0,
    fireDelay: 760 + Math.random() * 500,
  };
  const torsoMaterial = fpsArenaMaterial(torsoColor, 0.7, 0.04);
  const limbMaterial = fpsArenaMaterial(limbColor, 0.82, 0.02);
  const headMaterial = fpsArenaMaterial(headColor, 0.66, 0.02);
  fpsArenaRegisterHumanPart(state, root, new THREE.Mesh(new THREE.SphereGeometry(0.24, 20, 14), headMaterial), "head", 2, 80).position.set(0, 0.92, 0);
  fpsArenaRegisterHumanPart(state, root, new THREE.Mesh(new THREE.CapsuleGeometry(0.24, 0.65, 4, 12), torsoMaterial), "torso", 1, 0).position.set(0, 0.24, 0);
  const leftArm = fpsArenaRegisterHumanPart(state, root, new THREE.Mesh(new THREE.CapsuleGeometry(0.075, 0.62, 3, 8), limbMaterial), "arm");
  leftArm.position.set(-0.35, 0.25, 0);
  leftArm.rotation.z = 0.22;
  const rightArm = fpsArenaRegisterHumanPart(state, root, new THREE.Mesh(new THREE.CapsuleGeometry(0.075, 0.62, 3, 8), limbMaterial), "arm");
  rightArm.position.set(0.35, 0.25, 0);
  rightArm.rotation.z = -0.22;
  const leftLeg = fpsArenaRegisterHumanPart(state, root, new THREE.Mesh(new THREE.CapsuleGeometry(0.09, 0.72, 3, 8), limbMaterial), "leg");
  leftLeg.position.set(-0.14, -0.55, 0);
  leftLeg.rotation.z = -0.08;
  const rightLeg = fpsArenaRegisterHumanPart(state, root, new THREE.Mesh(new THREE.CapsuleGeometry(0.09, 0.72, 3, 8), limbMaterial), "leg");
  rightLeg.position.set(0.14, -0.55, 0);
  rightLeg.rotation.z = 0.08;
  const shoulder = fpsArenaRegisterHumanPart(state, root, new THREE.Mesh(new THREE.BoxGeometry(0.78, 0.12, 0.18), torsoMaterial), "torso");
  shoulder.position.set(0, 0.55, 0);
  state.scene.add(root);
  state.targets.push(root);
  return root;
}

function fpsArenaCreateBomb(state) {
  const site = Math.random() > 0.5 ? { x: -4.5, z: -14 } : { x: 4.8, z: -18 };
  const bomb = fpsArenaAddBox(state.scene, site.x, 0.45, site.z, 0.9, 0.65, 0.9, 0xfacc15);
  bomb.userData = { kind: "bomb", hp: 999, score: 0 };
  state.bomb = bomb;
  state.hittables.push(bomb);
  const beacon = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 2.4, 18), fpsArenaMaterial(0xfacc15, 0.35, 0.12));
  beacon.position.set(site.x, 1.7, site.z);
  state.scene.add(beacon);
}

function fpsArenaBotMuzzlePosition(bot) {
  const forward = new THREE.Vector3(0, 0, 1).applyQuaternion(bot.quaternion).normalize();
  const right = new THREE.Vector3(1, 0, 0).applyQuaternion(bot.quaternion).normalize();
  return bot.position.clone()
    .add(new THREE.Vector3(0, 0.45, 0))
    .add(forward.multiplyScalar(0.34))
    .add(right.multiplyScalar(0.18));
}

function fpsArenaLineOfSightClear(state, from, to) {
  if (!state.cover?.length) return true;
  const direction = to.clone().sub(from);
  const distance = direction.length();
  if (distance <= 0.001) return true;
  direction.normalize();
  const raycaster = new THREE.Raycaster(from, direction, 0.05, distance - 0.2);
  return raycaster.intersectObjects(state.cover, false).length === 0;
}

function fpsArenaAddTracer(state, from, to, hit) {
  const geometry = new THREE.BufferGeometry().setFromPoints([from, to]);
  const material = new THREE.LineBasicMaterial({
    color: hit ? 0xf97316 : 0xfacc15,
    transparent: true,
    opacity: hit ? 0.98 : 0.72,
  });
  const line = new THREE.Line(geometry, material);
  state.scene.add(line);
  state.botTracers.push({ object: line, expiresAt: performance.now() + 140 });
}

function fpsArenaCameraForward(state) {
  return new THREE.Vector3(0, 0, -1).applyQuaternion(state.camera.quaternion).normalize();
}

function fpsArenaPlayerMuzzlePosition(state) {
  const forward = fpsArenaCameraForward(state);
  const right = new THREE.Vector3(1, 0, 0).applyQuaternion(state.camera.quaternion).normalize();
  const down = new THREE.Vector3(0, -1, 0);
  return state.camera.position.clone()
    .add(forward.multiplyScalar(0.44))
    .add(right.multiplyScalar(0.16))
    .add(down.multiplyScalar(0.12));
}

function fpsArenaAddImpactSpark(state, position, color = 0xfef08a) {
  const spark = new THREE.Mesh(
    new THREE.SphereGeometry(0.08, 8, 6),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95 })
  );
  spark.position.copy(position);
  state.scene.add(spark);
  state.impactEffects.push({ object: spark, expiresAt: performance.now() + 120 });
}

function fpsArenaDisposeObject(object) {
  object?.traverse?.((child) => {
    child.geometry?.dispose?.();
    child.material?.dispose?.();
  });
  object?.geometry?.dispose?.();
  object?.material?.dispose?.();
}

function fpsArenaAddBloodSplatter(state, position, count = 16) {
  if (!position) return;
  for (let i = 0; i < count; i += 1) {
    const droplet = new THREE.Mesh(
      new THREE.SphereGeometry(0.025 + Math.random() * 0.035, 7, 5),
      new THREE.MeshBasicMaterial({ color: 0xb91c1c, transparent: true, opacity: 0.9 })
    );
    droplet.position.copy(position);
    state.scene.add(droplet);
    state.bloodEffects.push({
      object: droplet,
      velocity: new THREE.Vector3(
        (Math.random() - 0.5) * 3.2,
        1.2 + Math.random() * 2.6,
        (Math.random() - 0.5) * 3.2
      ),
      bornAt: performance.now(),
      expiresAt: performance.now() + 640 + Math.random() * 420,
    });
  }
}

function fpsArenaAddPlayerFireEffects(state, hitPoint, hitTarget = false) {
  const muzzle = fpsArenaPlayerMuzzlePosition(state);
  const endpoint = hitPoint || state.camera.position.clone().add(fpsArenaCameraForward(state).multiplyScalar(34));
  fpsArenaAddTracer(state, muzzle, endpoint, hitTarget);
  fpsArenaAddMuzzleFlash(state, muzzle, 0x93c5fd);
  if (hitPoint) fpsArenaAddImpactSpark(state, hitPoint, hitTarget ? 0xf97316 : 0xfef08a);
}

function fpsArenaAddBotProjectile(state, from, to, bot, dist) {
  const spread = 0.22 + dist * 0.018;
  const endpoint = to.clone().add(new THREE.Vector3(
    (Math.random() - 0.5) * spread,
    (Math.random() - 0.5) * spread * 0.7,
    (Math.random() - 0.5) * spread
  ));
  const velocity = endpoint.sub(from).normalize().multiplyScalar(18 + Math.random() * 7);
  const projectile = new THREE.Mesh(
    new THREE.SphereGeometry(0.065, 10, 8),
    new THREE.MeshBasicMaterial({ color: 0xfacc15, transparent: true, opacity: 0.95 })
  );
  projectile.position.copy(from);
  state.scene.add(projectile);
  state.botProjectiles.push({
    object: projectile,
    velocity,
    previous: from.clone(),
    damage: 8 + Math.random() * 5,
    owner: bot,
    expiresAt: performance.now() + 1800,
  });
}

function fpsArenaAddMuzzleFlash(state, position, color = 0xfef08a) {
  const flash = new THREE.Mesh(
    new THREE.SphereGeometry(0.09, 10, 8),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9 })
  );
  flash.position.copy(position);
  state.scene.add(flash);
  state.botMuzzleFlashes.push({ object: flash, expiresAt: performance.now() + 90 });
}

function fpsArenaEnsureAudio() {
  try {
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) return null;
    if (!fpsArenaAudioContext) fpsArenaAudioContext = new AudioContextCtor();
    if (fpsArenaAudioContext.state === "suspended") fpsArenaAudioContext.resume?.();
    return fpsArenaAudioContext;
  } catch {
    return null;
  }
}

function fpsArenaPlaySound(type) {
  const audio = fpsArenaEnsureAudio();
  if (!audio) return;
  const now = audio.currentTime;
  const gain = audio.createGain();
  const osc = audio.createOscillator();
  const settings = {
    fire: { type: "square", start: 160, end: 58, gain: 0.07, duration: 0.08 },
    botFire: { type: "sawtooth", start: 220, end: 85, gain: 0.045, duration: 0.07 },
    hit: { type: "triangle", start: 520, end: 260, gain: 0.04, duration: 0.09 },
    damage: { type: "sawtooth", start: 90, end: 44, gain: 0.08, duration: 0.12 },
    defuse: { type: "sine", start: 740, end: 980, gain: 0.035, duration: 0.12 },
    scream: { type: "sawtooth", start: 720, end: 115, gain: 0.075, duration: 0.34 },
  }[type] || { type: "square", start: 160, end: 70, gain: 0.05, duration: 0.08 };
  osc.type = settings.type;
  osc.frequency.setValueAtTime(settings.start, now);
  osc.frequency.exponentialRampToValueAtTime(Math.max(1, settings.end), now + settings.duration);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(settings.gain, now + 0.008);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + settings.duration);
  osc.connect(gain);
  gain.connect(audio.destination);
  osc.start(now);
  osc.stop(now + settings.duration + 0.02);
}

function fpsArenaAddShake(state, strength = 1, duration = 130) {
  state.shakeUntil = Math.max(state.shakeUntil || 0, performance.now() + duration);
  state.shakeDuration = Math.max(state.shakeDuration || 0, duration);
  state.shakeStrength = Math.max(state.shakeStrength || 0, strength);
  if (navigator.vibrate && strength >= 1.1) navigator.vibrate(Math.min(45, Math.round(duration / 4)));
}

function fpsArenaUpdateFeedback(state, now) {
  const stage = $("fps-arena-stage");
  const remainingShake = Math.max(0, state.shakeUntil - now);
  if (remainingShake > 0) {
    const falloff = remainingShake / Math.max(1, state.shakeDuration || 180);
    const strength = (state.shakeStrength || 0) * falloff;
    state.shakeVector.set(
      Math.sin(now * 0.055 + state.shakePhase) * strength,
      Math.cos(now * 0.071 + state.shakePhase) * strength
    );
  } else {
    state.shakeVector.set(0, 0);
    state.shakeStrength = 0;
  }
  if (stage) {
    stage.style.setProperty("--fps-shake-x", `${state.shakeVector.x * 4.8}px`);
    stage.style.setProperty("--fps-shake-y", `${state.shakeVector.y * 3.2}px`);
    const remainingDamage = Math.max(0, state.damageFlashUntil - now);
    stage.style.setProperty("--fps-damage-opacity", `${Math.min(0.75, remainingDamage / 360)}`);
    stage.style.setProperty("--fps-damage-angle", `${state.damageSourceAngle || 0}rad`);
  }
}

function fpsArenaSetDamageCue(state, from) {
  state.damageFlashUntil = performance.now() + 360;
  const angleToSource = Math.atan2(from.x - state.player.x, state.player.z - from.z);
  state.damageSourceAngle = angleToSource - state.yaw;
  fpsArenaAddShake(state, 1.45, 260);
  fpsArenaPlaySound("damage");
}

function fpsArenaUpdateBotFire(state, bot, dist, now) {
  if (dist > FPS_ARENA_BOT_FIRE_RANGE || now - bot.userData.lastAttack < bot.userData.fireDelay) return;
  const muzzle = fpsArenaBotMuzzlePosition(bot);
  const aimPoint = state.player.clone().add(new THREE.Vector3(0, -0.15, 0));
  if (!fpsArenaLineOfSightClear(state, muzzle, aimPoint)) return;
  bot.userData.lastAttack = now;
  bot.userData.fireDelay = 620 + Math.random() * 560;
  fpsArenaAddBotProjectile(state, muzzle, aimPoint, bot, dist);
  fpsArenaAddTracer(state, muzzle, aimPoint, false);
  fpsArenaAddMuzzleFlash(state, muzzle);
  fpsArenaPlaySound("botFire");
}

function fpsArenaPointSegmentDistance(point, start, end) {
  const segment = end.clone().sub(start);
  const lengthSq = segment.lengthSq();
  if (lengthSq <= 0.0001) return point.distanceTo(start);
  const t = Math.max(0, Math.min(1, point.clone().sub(start).dot(segment) / lengthSq));
  return point.distanceTo(start.clone().add(segment.multiplyScalar(t)));
}

function fpsArenaProjectileHitsCover(state, start, end) {
  const direction = end.clone().sub(start);
  const distance = direction.length();
  if (distance <= 0.001 || !state.cover?.length) return false;
  direction.normalize();
  const raycaster = new THREE.Raycaster(start, direction, 0, distance);
  return raycaster.intersectObjects(state.cover, false).length > 0;
}

function fpsArenaUpdateBotProjectiles(state, dt, now) {
  const playerCenter = state.player.clone().add(new THREE.Vector3(0, -0.38, 0));
  for (let i = state.botProjectiles.length - 1; i >= 0; i -= 1) {
    const projectile = state.botProjectiles[i];
    const object = projectile.object;
    projectile.previous.copy(object.position);
    object.position.add(projectile.velocity.clone().multiplyScalar(dt));
    if (fpsArenaProjectileHitsCover(state, projectile.previous, object.position)) {
      fpsArenaAddImpactSpark(state, object.position, 0xfacc15);
      state.scene.remove(object);
      object.geometry?.dispose?.();
      object.material?.dispose?.();
      state.botProjectiles.splice(i, 1);
      continue;
    }
    if (fpsArenaPointSegmentDistance(playerCenter, projectile.previous, object.position) < 0.42) {
      state.health -= projectile.damage;
      fpsArenaSetDamageCue(state, projectile.previous);
      state.scene.remove(object);
      object.geometry?.dispose?.();
      object.material?.dispose?.();
      state.botProjectiles.splice(i, 1);
      continue;
    }
    if (projectile.expiresAt <= now) {
      state.scene.remove(object);
      object.geometry?.dispose?.();
      object.material?.dispose?.();
      state.botProjectiles.splice(i, 1);
    }
  }
}

function fpsArenaUpdateCombatEffects(state, now) {
  const removeExpired = (items) => {
    for (let i = items.length - 1; i >= 0; i -= 1) {
      if (items[i].expiresAt > now) continue;
      const object = items[i].object;
      state.scene.remove(object);
      object.geometry?.dispose?.();
      object.material?.dispose?.();
      items.splice(i, 1);
    }
  };
  removeExpired(state.botTracers);
  removeExpired(state.botMuzzleFlashes);
  removeExpired(state.impactEffects);
  for (let i = state.bloodEffects.length - 1; i >= 0; i -= 1) {
    const item = state.bloodEffects[i];
    const dt = Math.min(0.04, Math.max(0.001, (now - (item.lastAt || now)) / 1000));
    item.lastAt = now;
    item.object.position.add(item.velocity.clone().multiplyScalar(dt));
    item.velocity.y -= 6.6 * dt;
    if (item.object.material) {
      item.object.material.opacity = Math.max(0, (item.expiresAt - now) / 720);
    }
    if (item.object.position.y < 0.04) {
      item.object.position.y = 0.04;
      item.velocity.y *= -0.18;
      item.velocity.x *= 0.78;
      item.velocity.z *= 0.78;
    }
    if (item.expiresAt > now) continue;
    state.scene.remove(item.object);
    fpsArenaDisposeObject(item.object);
    state.bloodEffects.splice(i, 1);
  }
  for (let i = state.deadBodies.length - 1; i >= 0; i -= 1) {
    const body = state.deadBodies[i];
    const progress = Math.min(1, (now - body.startedAt) / body.duration);
    body.object.rotation.x = body.baseRotation.x + body.fallDirection * progress * 1.34;
    body.object.rotation.z = body.baseRotation.z + body.sideRoll * progress * 0.64;
    body.object.position.y = Math.max(0.32, body.baseY - progress * 0.66);
    if (body.expiresAt > now) continue;
    state.scene.remove(body.object);
    fpsArenaDisposeObject(body.object);
    state.deadBodies.splice(i, 1);
  }
}

function fpsArenaResizeRenderer() {
  const state = fpsArenaState;
  const stage = $("fps-arena-stage");
  if (!state?.renderer || !state?.camera || !stage) return;
  const width = Math.max(320, Math.floor(stage.clientWidth || 640));
  const height = Math.max(240, Math.floor(stage.clientHeight || 360));
  state.renderer.setSize(width, height, false);
  state.camera.aspect = width / height;
  state.camera.updateProjectionMatrix();
}

function fpsArenaBuildCombatMap(scene) {
  const cover = [];
  const trackCover = (mesh, options = {}) => {
    mesh.userData = {
      ...mesh.userData,
      kind: "cover",
      blocksPlayer: options.blocksPlayer !== false,
    };
    cover.push(mesh);
    return mesh;
  };
  const addCoverBox = (...args) => trackCover(fpsArenaAddBox(scene, ...args));
  const addCoverCylinder = (...args) => trackCover(fpsArenaAddCylinder(scene, ...args));
  const addFloorMark = (x, z, sx, sz, color) => {
    const mark = fpsArenaAddBox(scene, x, 0.015, z, sx, 0.03, sz, color);
    mark.castShadow = false;
    return mark;
  };

  trackCover(fpsArenaAddBox(scene, -11.2, 1.5, -13, 0.35, 3, 42, 0x24324a));
  trackCover(fpsArenaAddBox(scene, 11.2, 1.5, -13, 0.35, 3, 42, 0x24324a));
  trackCover(fpsArenaAddBox(scene, 0, 1.5, -34.2, 22, 3, 0.35, 0x24324a));
  addFloorMark(0, -13, 0.12, 41, 0x1d4ed8);
  addFloorMark(-4.8, -18, 2.8, 0.12, 0xfacc15);
  addFloorMark(4.8, -22, 2.8, 0.12, 0xfacc15);

  addCoverBox(-5.6, 0.68, -5.3, 4.2, 1.35, 0.55, 0x334155);
  addCoverBox(5.6, 0.68, -5.3, 4.2, 1.35, 0.55, 0x334155);
  addCoverBox(-7.1, 0.95, -11.4, 1.45, 1.9, 6.3, 0x1f2937);
  addCoverBox(7.1, 0.95, -12.6, 1.45, 1.9, 6.8, 0x1f2937);
  addCoverBox(-2.1, 0.62, -12.8, 3.2, 1.24, 0.62, 0x475569);
  addCoverBox(2.4, 0.62, -16.2, 3.5, 1.24, 0.62, 0x475569);
  addCoverBox(-5.2, 0.82, -21.2, 4.4, 1.64, 1.15, 0x293548);
  addCoverBox(5.5, 0.82, -24.6, 4.7, 1.64, 1.15, 0x293548);
  addCoverBox(0, 0.58, -27.9, 5.4, 1.16, 0.62, 0x475569);
  addCoverBox(-8.9, 0.65, -28.6, 2.6, 1.3, 1.2, 0x334155);
  addCoverBox(8.8, 0.65, -8.4, 2.4, 1.3, 1.2, 0x334155);

  for (const x of [-8.5, 8.5]) {
    for (const z of [-8.3, -18.5, -29.2]) {
      addCoverCylinder(x, 1.15, z, 0.42, 2.3, 0x334155);
    }
  }
  [
    [-3.8, -8.8], [-2.7, -9.7], [3.4, -9.4], [4.5, -10.3],
    [-1.3, -19.8], [0.1, -20.7], [1.4, -19.8], [-7.1, -24.4], [7.2, -19.6],
  ].forEach(([x, z], index) => {
    addCoverBox(x, 0.52, z, 1.0, 1.04, 1.0, index % 2 ? 0x3f3f46 : 0x334155);
  });

  fpsArenaAddBox(scene, 0, 2.85, -14.8, 18, 0.22, 0.24, 0x1e293b);
  fpsArenaAddBox(scene, 0, 2.85, -25.8, 18, 0.22, 0.24, 0x1e293b);
  fpsArenaAddBox(scene, -4.8, 0.04, -14, 2.8, 0.04, 2.8, 0x78350f);
  fpsArenaAddBox(scene, 4.8, 0.04, -18, 2.8, 0.04, 2.8, 0x78350f);

  return {
    cover,
    spawnPoints: [
      { x: -7.8, z: -7.2 }, { x: -3.4, z: -8.8 }, { x: 3.2, z: -9.2 }, { x: 8.2, z: -10.8 },
      { x: -8.1, z: -17.6 }, { x: -2.2, z: -18.6 }, { x: 3.1, z: -20.2 }, { x: 8.1, z: -22.4 },
      { x: -6.9, z: -27.2 }, { x: 0.1, z: -30.6 }, { x: 6.7, z: -28.6 },
    ],
  };
}

function createFpsArenaWorld(mode) {
  const stage = $("fps-arena-stage");
  if (!stage || typeof THREE === "undefined") return null;
  const dailyChallenge = window.hackmeGameDailyChallenge?.("fps_arena") || null;
  stage.querySelectorAll("canvas").forEach((canvas) => canvas.remove());
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x08111f);
  scene.fog = new THREE.Fog(0x08111f, 12, 42);
  const camera = new THREE.PerspectiveCamera(72, 16 / 9, 0.1, 100);
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance", preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.shadowMap.enabled = true;
  stage.prepend(renderer.domElement);

  scene.add(new THREE.HemisphereLight(0xdbeafe, 0x111827, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 1.8);
  key.position.set(4, 8, 5);
  key.castShadow = true;
  scene.add(key);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(22, 42), fpsArenaMaterial(0x162033, 0.9, 0.02));
  floor.rotation.x = -Math.PI / 2;
  floor.position.z = -13;
  floor.receiveShadow = true;
  scene.add(floor);
  const grid = new THREE.GridHelper(22, 22, 0x38bdf8, 0x26364f);
  grid.position.z = -13;
  scene.add(grid);
  const map = fpsArenaBuildCombatMap(scene);

  const state = {
    status: "active",
    mode,
    scene,
    camera,
    renderer,
    hittables: [],
    targets: [],
    cover: map.cover,
    spawnPoints: map.spawnPoints,
    botTracers: [],
    botMuzzleFlashes: [],
    botProjectiles: [],
    impactEffects: [],
    bloodEffects: [],
    deadBodies: [],
    startedAt: Date.now(),
    completedAt: null,
    durationMs: FPS_ARENA_MODES[mode].seconds * 1000,
    penaltySeconds: 0,
    scoreSubmitted: false,
    difficulty: mode,
    puzzleId: dailyChallenge?.key || `fps-arena-${mode}`,
    dailyChallenge,
    score: 0,
    health: FPS_ARENA_MODES[mode].health,
    shots: 0,
    hits: 0,
    yaw: 0,
    pitch: -0.03,
    breathPhase: Math.random() * Math.PI * 2,
    breathOffset: new THREE.Vector2(0, 0),
    player: new THREE.Vector3(0, 1.65, 1.5),
    velocity: new THREE.Vector3(),
    keys: {},
    stamina: 100,
    mobileSprint: false,
    running: false,
    lastFrame: performance.now(),
    lastSpawnAt: 0,
    lastShotAt: 0,
    weaponIndex: 0,
    weapon: FPS_ARENA_WEAPONS[0],
    ammo: FPS_ARENA_WEAPONS[0].mag,
    reserve: FPS_ARENA_WEAPONS[0].reserve,
    reloadingUntil: 0,
    recoilKick: 0,
    damageFlashUntil: 0,
    damageSourceAngle: 0,
    shakeUntil: 0,
    shakeDuration: 180,
    shakeStrength: 0,
    shakePhase: Math.random() * Math.PI * 2,
    shakeVector: new THREE.Vector2(0, 0),
    defuseProgress: 0,
    bomb: null,
  };
  fpsArenaState = state;
  fpsArenaResizeRenderer();
  fpsArenaResizeObserver = new ResizeObserver(fpsArenaResizeRenderer);
  fpsArenaResizeObserver.observe(stage);
  if (mode === "aim") {
    for (let i = 0; i < 7; i += 1) fpsArenaAddTarget(state, "target");
  } else if (mode === "pve") {
    for (let i = 0; i < 4; i += 1) fpsArenaAddTarget(state, "enemy", { hp: 2, speed: 0.9 + i * 0.08 });
  } else if (mode === "bomb") {
    fpsArenaCreateBomb(state);
    for (let i = 0; i < 3; i += 1) fpsArenaAddTarget(state, "enemy", { hp: 2, speed: 0.85 });
  } else if (mode === "bot") {
    for (let i = 0; i < 5; i += 1) fpsArenaAddTarget(state, "bot", { hp: 2, speed: 1.1, score: 220 });
  }
  return state;
}

function renderFpsArenaBoard() {
  const stage = $("fps-arena-stage");
  if (!stage) return;
  if (typeof THREE === "undefined") {
    stage.querySelectorAll("canvas").forEach((canvas) => canvas.remove());
    const hud = $("fps-arena-hud");
    if (hud) hud.textContent = "Three.js 載入失敗，無法啟動 3D 模式";
    return;
  }
  if (!fpsArenaState) {
    updateFpsArenaHud();
  } else {
    fpsArenaResizeRenderer();
  }
}

function startFpsArenaGame() {
  disposeFpsArenaScene();
  const mode = fpsArenaMode();
  const state = createFpsArenaWorld(mode);
  if (!state) {
    setGameMsg("3D 射擊場初始化失敗", false);
    return;
  }
  updateFpsArenaStatus("任務開始。");
  if (typeof ensureSoloGameTimer === "function") ensureSoloGameTimer();
  fpsArenaLoop(performance.now());
}

function finishFpsArenaGame(reason = "time") {
  const state = fpsArenaState;
  if (!state || state.status === "finished") return;
  state.status = "finished";
  state.completedAt = Date.now();
  if (reason === "defused") state.score += 900 + Math.ceil(state.health * 3);
  if (reason === "time" && state.health > 0) state.score += Math.ceil(state.health);
  updateFpsArenaStatus();
  updateFpsArenaHud();
  if (Number(state.score || 0) > 0 && typeof submitSoloGameScore === "function") {
    const accuracy = state.shots > 0 ? Math.round((state.hits / state.shots) * 100) : 0;
    if (accuracy >= 45) window.recordHackmeGameAchievement?.("fps_arena", "accuracy", "穩定射手", "命中率達 45%。");
    if (reason === "defused") window.recordHackmeGameAchievement?.("fps_arena", "defuse", "拆彈成功", "完成 Bomb Defuse。");
    submitSoloGameScore("fps_arena", state);
  }
  if (typeof stopSoloGameTimerIfIdle === "function") stopSoloGameTimerIfIdle();
  const label = reason === "defused" ? "拆彈成功" : reason === "health" ? "任務失敗" : "任務結束";
  setGameMsg(`${label}，分數 ${Number(state.score || 0).toLocaleString()}`, reason !== "health");
}

function fpsArenaApplyCamera(state) {
  state.camera.position.copy(state.player);
  state.camera.position.x += (state.shakeVector?.x || 0) * 0.025;
  state.camera.position.y += (state.shakeVector?.y || 0) * 0.018;
  state.camera.rotation.order = "YXZ";
  state.camera.rotation.y = state.yaw + (state.breathOffset?.x || 0);
  state.camera.rotation.x = state.pitch + (state.breathOffset?.y || 0) - (state.recoilKick || 0);
  state.camera.rotation.z = (state.shakeVector?.x || 0) * 0.01;
}

function fpsArenaUpdateBreathing(state, now) {
  const t = now * 0.0017 + state.breathPhase;
  const moving = state.keys.w || state.keys.a || state.keys.s || state.keys.d || state.keys.ArrowUp || state.keys.ArrowDown || state.keys.ArrowLeft || state.keys.ArrowRight;
  const runScale = state.running ? 2.85 : moving ? 1.8 : 1;
  const intensity = FPS_ARENA_SCOPE_SWAY * runScale;
  state.breathOffset.set(Math.sin(t) * intensity, Math.cos(t * 0.72) * intensity * 0.78);
  const stage = $("fps-arena-stage");
  if (stage) {
    stage.style.setProperty("--fps-breathe-x", `${Math.sin(t) * (state.running ? 9.2 : moving ? 5.5 : 3.2)}px`);
    stage.style.setProperty("--fps-breathe-y", `${Math.cos(t * 0.72) * (state.running ? 7.2 : moving ? 4.4 : 2.4)}px`);
    stage.style.setProperty("--fps-breathe-rot", `${Math.sin(t * 0.48) * (state.running ? 2.8 : moving ? 1.8 : 1.1)}deg`);
    stage.style.setProperty("--fps-breathe-scale", `${1 + Math.sin(t * 1.16) * (state.running ? 0.06 : moving ? 0.042 : 0.026)}`);
  }
}

function fpsArenaClampPlayerToMap(state, position) {
  position.x = Math.max(-9.8, Math.min(9.8, position.x));
  position.z = Math.max(-31.2, Math.min(2.8, position.z));
  return position;
}

function fpsArenaPositionBlocked(state, position) {
  const cover = state.cover || [];
  for (const object of cover) {
    if (object.userData?.blocksPlayer === false) continue;
    const box = new THREE.Box3().setFromObject(object);
    if (position.y < box.min.y - 0.2 || position.y > box.max.y + 2.2) continue;
    const closestX = Math.max(box.min.x, Math.min(position.x, box.max.x));
    const closestZ = Math.max(box.min.z, Math.min(position.z, box.max.z));
    const dx = position.x - closestX;
    const dz = position.z - closestZ;
    if ((dx * dx) + (dz * dz) < FPS_ARENA_PLAYER_RADIUS * FPS_ARENA_PLAYER_RADIUS) return true;
  }
  return false;
}

function fpsArenaMoveWithCollision(state, delta) {
  const next = fpsArenaClampPlayerToMap(state, state.player.clone().add(delta));
  if (!fpsArenaPositionBlocked(state, next)) {
    state.player.copy(next);
    return;
  }
  const xOnly = fpsArenaClampPlayerToMap(state, state.player.clone().add(new THREE.Vector3(delta.x, 0, 0)));
  if (!fpsArenaPositionBlocked(state, xOnly)) state.player.copy(xOnly);
  const zOnly = fpsArenaClampPlayerToMap(state, state.player.clone().add(new THREE.Vector3(0, 0, delta.z)));
  if (!fpsArenaPositionBlocked(state, zOnly)) state.player.copy(zOnly);
}

function fpsArenaMovePlayer(state, dt) {
  const forward = new THREE.Vector3(Math.sin(state.yaw), 0, Math.cos(state.yaw) * -1);
  const right = new THREE.Vector3(Math.cos(state.yaw), 0, Math.sin(state.yaw));
  const move = new THREE.Vector3();
  if (state.keys.w || state.keys.ArrowUp) move.add(forward);
  if (state.keys.s || state.keys.ArrowDown) move.sub(forward);
  if (state.keys.d || state.keys.ArrowRight) move.add(right);
  if (state.keys.a || state.keys.ArrowLeft) move.sub(right);
  const moving = move.lengthSq() > 0;
  const sprintKey = state.keys.Shift || state.keys.shift || state.mobileSprint;
  const running = moving && sprintKey && state.stamina > 4;
  state.running = running;
  if (moving) {
    const speed = running ? 9.2 : 6.2;
    move.normalize().multiplyScalar(speed * dt);
    fpsArenaMoveWithCollision(state, move);
  }
  if (running) {
    state.stamina = Math.max(0, state.stamina - 34 * dt);
  } else {
    state.stamina = Math.min(100, state.stamina + (moving ? 14 : 22) * dt);
  }
  if (state.stamina <= 0) state.mobileSprint = false;
}

function fpsArenaRemoveObject(state, object) {
  const root = object?.userData?.root || object;
  state.scene.remove(root);
  state.targets = state.targets.filter((item) => item !== root);
  state.hittables = state.hittables.filter((item) => item !== root && item.userData?.root !== root);
  fpsArenaDisposeObject(root);
}

function fpsArenaKillTarget(state, target, hitPoint) {
  const root = target?.userData?.root || target;
  if (!root || root.userData.dead) return;
  const now = performance.now();
  root.userData.dead = true;
  state.targets = state.targets.filter((item) => item !== root);
  state.hittables = state.hittables.filter((item) => item !== root && item.userData?.root !== root);
  fpsArenaAddBloodSplatter(state, hitPoint || root.position.clone().add(new THREE.Vector3(0, 0.55, 0)), 24);
  fpsArenaAddShake(state, 1.05, 190);
  fpsArenaPlaySound("scream");
  state.deadBodies.push({
    object: root,
    startedAt: now,
    duration: 520,
    expiresAt: now + 4200,
    baseY: root.position.y,
    baseRotation: root.rotation.clone(),
    fallDirection: Math.random() > 0.5 ? 1 : -1,
    sideRoll: Math.random() - 0.5,
  });
}

function shootFpsArena() {
  const state = fpsArenaState;
  if (!state || state.status !== "active") return;
  const now = performance.now();
  const weapon = state.weapon || FPS_ARENA_WEAPONS[0];
  if (state.reloadingUntil && now < state.reloadingUntil) return;
  if (state.ammo <= 0) {
    reloadFpsArena();
    return;
  }
  if (now - state.lastShotAt < weapon.delay) return;
  state.lastShotAt = now;
  state.ammo -= 1;
  state.shots += 1;
  fpsArenaAddShake(state, 0.85, 150);
  fpsArenaPlaySound("fire");
  state.pitch = Math.max(-1.25, state.pitch - weapon.recoil);
  state.recoilKick = Math.min(0.08, (state.recoilKick || 0) + weapon.recoil * 0.55);
  const raycaster = new THREE.Raycaster();
  const spread = weapon.spread + (state.running ? 0.006 : 0) + Math.min(0.01, (state.recoilKick || 0) * 0.12);
  raycaster.setFromCamera(new THREE.Vector2((Math.random() - 0.5) * spread, (Math.random() - 0.5) * spread), state.camera);
  const hit = raycaster.intersectObjects([...state.hittables, ...state.cover], false)[0];
  const hitCover = Boolean(hit && state.cover.includes(hit.object));
  fpsArenaAddPlayerFireEffects(state, hit?.point, Boolean(hit && !hitCover));
  if (!hit || hitCover) {
    updateFpsArenaStatus();
    return;
  }
  const mesh = hit.object;
  const target = mesh.userData.root || mesh;
  const data = target.userData || mesh.userData;
  if (data.kind === "bomb" || mesh.userData.kind === "bomb") {
    fpsArenaPlaySound("defuse");
    attemptFpsArenaDefuse(true);
    return;
  }
  state.hits += 1;
  if (mesh.userData.part === "head") window.recordHackmeGameAchievement?.("fps_arena", "headshot", "爆頭訓練", "命中頭部。");
  fpsArenaPlaySound("hit");
  fpsArenaAddBloodSplatter(state, hit.point, data.hp <= 1 ? 18 : 7);
  data.hp -= (mesh.userData.damage || 1) * (weapon.damage || 1);
  state.score += Math.max(20, Math.round((data.score || 100) / 3)) + Number(mesh.userData.scoreBonus || 0);
  target.scale.multiplyScalar(0.94);
  if (data.hp <= 0) {
    state.score += data.score || 100;
    const kind = data.kind;
    fpsArenaKillTarget(state, target, hit.point);
    if (kind === "target") fpsArenaAddTarget(state, "target");
  }
  updateFpsArenaStatus();
}

function reloadFpsArena() {
  const state = fpsArenaState;
  if (!state || state.status !== "active") return;
  const weapon = state.weapon || FPS_ARENA_WEAPONS[0];
  if (state.ammo >= weapon.mag || state.reserve <= 0 || (state.reloadingUntil && performance.now() < state.reloadingUntil)) return;
  state.reloadingUntil = performance.now() + 980;
  window.setTimeout(() => {
    const current = fpsArenaState;
    if (!current || current !== state || current.status !== "active") return;
    const need = weapon.mag - current.ammo;
    const loaded = Math.min(need, current.reserve);
    current.ammo += loaded;
    current.reserve -= loaded;
    current.reloadingUntil = 0;
    updateFpsArenaStatus("換彈完成。");
  }, 990);
  updateFpsArenaStatus("換彈中。");
}

function switchFpsArenaWeapon() {
  const state = fpsArenaState;
  if (!state || state.status !== "active") return;
  state.weaponIndex = (Number(state.weaponIndex || 0) + 1) % FPS_ARENA_WEAPONS.length;
  state.weapon = FPS_ARENA_WEAPONS[state.weaponIndex];
  state.ammo = state.weapon.mag;
  state.reserve = state.weapon.reserve;
  state.reloadingUntil = 0;
  updateFpsArenaStatus(`切換武器：${state.weapon.label}`);
}

function attemptFpsArenaDefuse(fromShot = false) {
  const state = fpsArenaState;
  if (!state || state.status !== "active" || state.mode !== "bomb" || !state.bomb) return;
  const distance = state.player.distanceTo(state.bomb.position);
  if (distance > 3.2) {
    if (!fromShot) setGameMsg("距離炸彈太遠", false);
    return;
  }
  state.defuseProgress += fromShot ? 18 : 28;
  state.score += 35;
  updateFpsArenaStatus("正在拆彈。");
  if (state.defuseProgress >= 100) finishFpsArenaGame("defused");
}

function fpsArenaUpdateTargets(state, dt, now) {
  state.targets.forEach((mesh) => {
    const kind = mesh.userData.kind;
    if (kind === "target") {
      mesh.userData.phase += dt * 1.8;
      mesh.position.x += Math.sin(mesh.userData.phase) * dt * 1.2;
      mesh.position.y = mesh.userData.baseY + Math.sin(mesh.userData.phase * 1.7) * 0.25;
      mesh.rotation.y += dt * 1.2;
    } else if (kind === "enemy" || kind === "bot") {
      const toPlayer = new THREE.Vector3(state.player.x - mesh.position.x, 0, state.player.z - mesh.position.z);
      const dist = Math.max(0.001, toPlayer.length());
      toPlayer.normalize();
      const strafe = new THREE.Vector3(-toPlayer.z, 0, toPlayer.x).multiplyScalar(Math.sin(now * 0.002 + mesh.userData.phase) * 0.75);
      const speed = (kind === "bot" ? 1.4 : 1.05) * (mesh.userData.speed || 1);
      const botRangeControl = kind === "bot" && dist < 6.5 ? -0.65 : 1;
      mesh.position.add(toPlayer.multiplyScalar(speed * botRangeControl * dt));
      mesh.position.add(strafe.multiplyScalar(dt));
      mesh.position.x = Math.max(-9.5, Math.min(9.5, mesh.position.x));
      mesh.position.z = Math.max(-32, Math.min(1.8, mesh.position.z));
      mesh.lookAt(state.player.x, mesh.position.y, state.player.z);
      if (dist < 1.1) {
        state.health -= kind === "bot" ? 16 * dt : 24 * dt;
      }
      if (kind === "bot") fpsArenaUpdateBotFire(state, mesh, dist, now);
    }
    mesh.userData.breathPhase += dt * 2.2;
    mesh.scale.y = 1 + Math.sin(mesh.userData.breathPhase) * 0.018;
  });
  if (state.bomb) state.bomb.rotation.y += dt * 1.6;
}

function fpsArenaMaybeSpawn(state, now) {
  if (state.mode === "aim") return;
  const interval = state.mode === "bot" ? 4200 : state.mode === "bomb" ? 5200 : 2600;
  if (now - state.lastSpawnAt < interval) return;
  state.lastSpawnAt = now;
  const count = state.targets.filter((mesh) => mesh.userData.kind === "enemy" || mesh.userData.kind === "bot").length;
  const maxCount = state.mode === "bot" ? 6 : state.mode === "bomb" ? 5 : 8;
  if (count >= maxCount) return;
  fpsArenaAddTarget(state, state.mode === "bot" ? "bot" : "enemy", { hp: state.mode === "bot" ? 2 : 1 + Math.floor(Math.random() * 2) });
}

function fpsArenaLoop(now) {
  const state = fpsArenaState;
  if (!state?.renderer || !state?.scene || !state?.camera) return;
  const dt = Math.min(0.04, Math.max(0.001, (now - state.lastFrame) / 1000));
  state.lastFrame = now;
  if (state.status === "active") {
    fpsArenaMovePlayer(state, dt);
    fpsArenaUpdateBreathing(state, now);
    fpsArenaUpdateFeedback(state, now);
    state.recoilKick = Math.max(0, (state.recoilKick || 0) - dt * 0.08);
    fpsArenaApplyCamera(state);
    fpsArenaUpdateTargets(state, dt, now);
    fpsArenaUpdateBotProjectiles(state, dt, now);
    fpsArenaUpdateCombatEffects(state, now);
    fpsArenaMaybeSpawn(state, now);
    if (state.keys[" "] || state.keys.Spacebar) shootFpsArena();
    if (state.keys.e || state.keys.E) attemptFpsArenaDefuse();
    if (Date.now() - state.startedAt >= state.durationMs) finishFpsArenaGame("time");
    if (state.health <= 0) finishFpsArenaGame("health");
    updateFpsArenaHud();
  }
  state.renderer.render(state.scene, state.camera);
  fpsArenaRaf = requestAnimationFrame(fpsArenaLoop);
}

function handleFpsArenaKey(event, pressed) {
  const state = fpsArenaState;
  if (!state || state.status !== "active") return;
    if (["w", "a", "s", "d", "W", "A", "S", "D", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " ", "Spacebar", "e", "E", "r", "R", "q", "Q", "Shift"].includes(event.key)) {
      event.preventDefault();
      state.keys[event.key.length === 1 ? event.key.toLowerCase() : event.key] = pressed;
    }
  if (pressed && (event.key === "r" || event.key === "R")) reloadFpsArena();
  if (pressed && (event.key === "q" || event.key === "Q")) switchFpsArenaWeapon();
}

function handleFpsArenaTouch(action) {
  const state = fpsArenaState;
  if (!state || state.status !== "active") return;
  if (action === "fps-fire") return shootFpsArena();
  if (action === "fps-reload") return reloadFpsArena();
  if (action === "fps-weapon") return switchFpsArenaWeapon();
  if (action === "fps-sprint") {
    state.mobileSprint = !state.mobileSprint;
    updateFpsArenaStatus(state.mobileSprint ? "衝刺啟動。" : "衝刺關閉。");
    return;
  }
  const impulse = 0.82;
  const forward = new THREE.Vector3(Math.sin(state.yaw), 0, Math.cos(state.yaw) * -1);
  const right = new THREE.Vector3(Math.cos(state.yaw), 0, Math.sin(state.yaw));
  if (action === "fps-forward") fpsArenaMoveWithCollision(state, forward.multiplyScalar(impulse));
  if (action === "fps-back") fpsArenaMoveWithCollision(state, forward.multiplyScalar(-impulse));
  if (action === "fps-right") fpsArenaMoveWithCollision(state, right.multiplyScalar(impulse));
  if (action === "fps-left") fpsArenaMoveWithCollision(state, right.multiplyScalar(-impulse));
}

function fpsArenaApplyLookDelta(state, dx, dy) {
  if (!state || (!dx && !dy)) return;
  state.yaw -= dx * 0.0024;
  state.pitch = Math.max(-1.25, Math.min(1.05, state.pitch - dy * 0.0024));
}

function handleFpsArenaPointerMove(event) {
  const state = fpsArenaState;
  if (!state || state.status !== "active") return;
  let dx = event.movementX || 0;
  let dy = event.movementY || 0;
  if (!document.pointerLockElement && fpsArenaPointerDragging && fpsArenaLastPointer) {
    dx = event.clientX - fpsArenaLastPointer.x;
    dy = event.clientY - fpsArenaLastPointer.y;
    fpsArenaLastPointer = { x: event.clientX, y: event.clientY };
  }
  if (!dx && !dy) return;
  fpsArenaApplyLookDelta(state, dx, dy);
}

function handleFpsArenaTouchPointerDown(event) {
  if (event.pointerType === "mouse") return;
  const stage = event.target?.closest?.("#fps-arena-stage");
  if (!stage || !fpsArenaState || fpsArenaState.status !== "active") return;
  event.preventDefault();
  fpsArenaTouchPointerId = event.pointerId;
  fpsArenaTouchMoved = false;
  fpsArenaLastPointer = { x: event.clientX, y: event.clientY };
  try {
    stage.setPointerCapture?.(event.pointerId);
  } catch (err) {}
}

function handleFpsArenaTouchPointerMove(event) {
  if (event.pointerType === "mouse" || fpsArenaTouchPointerId !== event.pointerId || !fpsArenaLastPointer) return;
  const state = fpsArenaState;
  if (!state || state.status !== "active") return;
  event.preventDefault();
  const dx = event.clientX - fpsArenaLastPointer.x;
  const dy = event.clientY - fpsArenaLastPointer.y;
  if (Math.hypot(dx, dy) > 3) fpsArenaTouchMoved = true;
  fpsArenaLastPointer = { x: event.clientX, y: event.clientY };
  fpsArenaApplyLookDelta(state, dx, dy);
}

function handleFpsArenaTouchPointerEnd(event) {
  if (event.pointerType === "mouse" || fpsArenaTouchPointerId !== event.pointerId) return;
  const stage = event.target?.closest?.("#fps-arena-stage");
  event.preventDefault();
  if (event.type === "pointerup" && !fpsArenaTouchMoved) shootFpsArena();
  try {
    stage?.releasePointerCapture?.(event.pointerId);
  } catch (err) {}
  fpsArenaTouchPointerId = null;
  fpsArenaTouchMoved = false;
  fpsArenaLastPointer = null;
}

document.addEventListener("mousemove", handleFpsArenaPointerMove);
document.addEventListener("mouseup", () => {
  fpsArenaPointerDragging = false;
  fpsArenaLastPointer = null;
});
document.addEventListener("mousedown", (event) => {
  const stage = event.target?.closest?.("#fps-arena-stage");
  if (!stage || !fpsArenaState || fpsArenaState.status !== "active") return;
  event.preventDefault();
  fpsArenaPointerDragging = true;
  fpsArenaLastPointer = { x: event.clientX, y: event.clientY };
  if (stage.requestPointerLock && !document.pointerLockElement) stage.requestPointerLock();
  if (event.button === 0) shootFpsArena();
});
document.addEventListener("pointerdown", handleFpsArenaTouchPointerDown);
document.addEventListener("pointermove", handleFpsArenaTouchPointerMove);
document.addEventListener("pointerup", handleFpsArenaTouchPointerEnd);
document.addEventListener("pointercancel", handleFpsArenaTouchPointerEnd);

window.addEventListener("resize", fpsArenaResizeRenderer);
window.currentFpsArenaMode = fpsArenaMode;
window.isFpsArenaActive = isFpsArenaActive;
window.renderFpsArenaBoard = renderFpsArenaBoard;
window.updateFpsArenaStatus = updateFpsArenaStatus;
window.startFpsArenaGame = startFpsArenaGame;
window.finishFpsArenaGame = finishFpsArenaGame;
window.handleFpsArenaKey = handleFpsArenaKey;
window.handleFpsArenaTouch = handleFpsArenaTouch;
