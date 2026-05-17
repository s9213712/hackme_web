# Experiment Area Re-Audit

## Scope

Re-audited the new `experiments` SPA module after the fluid-mechanics / performance review. The pass focused on simulation correctness, interaction lifecycle, low-CPU Canvas behavior, mobile layout, and the no-backend/no-DB/no-worker requirement.

## Findings Fixed

1. Airplane stall behavior was too optimistic.
   - Fix: post-stall lift now drops as stall risk rises, while drag increases with stall and spoiler use.
   - Verification: high angle of attack + full flap + low speed produced `stall=100%` and reduced lift from `92` to `2`.

2. Liquid free surface rotated with the cup and pouring did not remove visible liquid.
   - Fix: the cup outline rotates, but the rendered liquid surface is clipped in world-horizontal coordinates; excessive positive or negative tilt removes visible particles.
   - Verification: negative tilt reduced visible particles from `240` to `233` in the Playwright smoke.

3. Liquid reset kept the previous tilted state and immediately continued spilling.
   - Fix: reset now returns cup tilt to `0`, clears shake, reseeds liquid, and redraws immediately.
   - Verification: reset restored visible particles to `240`.

4. Hummingbird wingbeat visualization aliased true wingbeat frequency.
   - Fix: the animation uses a slow-motion visual phase while KPI keeps true cycle time.
   - Verification: `52 Hz` displayed `19.2 ms`; `80 Hz` displayed `12.5 ms`.

5. Animation pause still kept a requestAnimationFrame loop alive.
   - Fix: pause now cancels the pending frame and resume restarts the loop.
   - Verification: rAF scheduled count stayed stable while paused: `29 -> 29`, then resumed to `38`.

6. Per-frame Canvas sizing and liquid shake time lookup were doing avoidable work.
   - Fix: Canvas dimensions/context are cached after forced resize; liquid update receives frame time instead of calling `performance.now()` per particle.

7. Mobile controls had a narrow overflow risk.
   - Fix: experiment controls now constrain range inputs with `min-width: 0` and `max-width: calc(100% - 2px)`.
   - Verification: 390px mobile viewport reported no overflowing experiment elements.

## Current Re-Audit Result

No new confirmed issues remain in the scoped Experiment Area checks.

The module remains an educational approximation only. It is not CFD, SPH, Navier-Stokes, aircraft certification math, or a biological neural-control model.

## Verification

- `node --check public/js/42-experiments.js`
- `node --check public/js/05-i18n.js`
- `python3 -m py_compile server.py routes/public.py`
- `git diff --check`
- Static scan found no `fetch`, `apiFetch`, `XMLHttpRequest`, `eval`, or `Function` usage in `public/js/42-experiments.js`.
- Playwright mounted the actual Experiment Area DOM/CSS/JS without Flask and verified:
  - Three sub-tabs switch correctly.
  - Plane KPIs respond to controls and post-stall lift drops.
  - Liquid spills under excessive positive/negative tilt and reset restores the pool.
  - Hummingbird KPI reports true wingbeat cycle while animation remains slow-motion.
  - Pause stops the animation loop; resume restarts it.
  - No `/api/` calls were made.
  - No console errors were observed.
  - 390px mobile viewport had no horizontal overflow.

## Performance Snapshot

Measured with Chromium Performance metrics over 1 second per stage:

- Airplane: task `0.1304s`, script `0.0216s`, layout `0.0088s`, heap `4.24 MiB`
- Liquid: task `0.1756s`, script `0.0150s`, layout `0.0094s`, heap `2.98 MiB`
- Hummingbird: task `0.1421s`, script `0.0214s`, layout `0.0102s`, heap `2.66 MiB`

These values are acceptable for the current low-particle educational Canvas design.

## Residual Notes

- The client navigation limits the module to `root` or internal-test token sessions with `feature_experiments_enabled`; because the requirement explicitly avoided backend routes/DB, this is not a server-side authorization boundary.
- If this later becomes a graded science/engineering tool, replace the heuristic models with validated equations or a dedicated simulation service. Do not silently present the current visuals as engineering-grade results.
