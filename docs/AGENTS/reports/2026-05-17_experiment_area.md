# Experiment Area Frontend Module

## Scope

Added a new `experiments` single-page app module for lightweight educational Canvas / WebGL simulations. The module is intentionally frontend-only: it does not create backend jobs, DB tables, migrations, Flask routes, or background workers.

The simulations now start in static-preview mode. Opening the module, switching sub-tabs, or changing controls draws a single preview frame only; the continuous `requestAnimationFrame` loop starts only after the user presses `開始模擬`, and it stops when the user pauses, switches experiment tabs, hides the browser tab, or leaves the module.

Access is limited in the client navigation to:

- `root`
- `internal_test` token sessions whose token feature scope allows `feature_experiments_enabled`

## Files Changed

- `public/index.html`
- `public/experiments.css`
- `public/js/42-experiments.js`
- `public/js/00-core.js`
- `public/js/50-admin.js`
- `public/js/90-bootstrap.js`
- `public/js/01-root-quick-settings.js`
- `routes/public.py`
- `services/platform/settings.py`
- `docs/AGENTS/reports/2026-05-17_experiment_area.md`

## Simulation Modules

1. Airplane airflow
   - Controls: angle of attack, flap / wing tilt, headwind, aircraft speed, spoiler, vortex / wingtip disturbance.
   - KPIs: relative lift, relative drag, stall risk.
   - The airplane view now lazy-loads the local Three.js bundle only when the user starts the simulation, renders a simplified 3D airplane model, supports mouse drag / touch swipe orbit control, and uses triangular airflow markers to show direction and relative strength.

2. Liquid molecules
   - Controls: cup tilt, viscosity, liquid level.
   - Actions: shake cup, glass-rod stir, pour cup, drop object, reset liquid.
   - KPIs: molecular kinetic energy, visible particle count, object count.
   - The liquid view was redesigned to keep molecules suspended inside the current liquid volume. The cup can tilt while the surface remains visually horizontal, and only dropped objects behave like sinking solids.

## Important Limitation

These simulations are educational approximations. They are not CFD, SPH, Navier-Stokes, engineering-grade fluid simulation, real aircraft performance calculation, or biological neural-control modeling. The airplane module uses simplified browser-side 3D geometry and visual airflow indicators; it is not a validated aerodynamic solver. The liquid module uses a stable educational particle field, not a real incompressible-flow solver.

## Verification

Completed checks for this change:

- `node --check public/js/42-experiments.js`
- `python3 -m py_compile server.py routes/public.py`
- `git diff --check`
- Static Playwright smoke without Flask: mounted the Experiment Area DOM/CSS/JS in a headless browser, activated the module, switched the experiment tabs, and confirmed KPI values updated.

Manual smoke checklist:

- Log in as an allowed account and confirm the sidebar shows `實驗區`.
- Switch both experiment tabs.
- Confirm each Canvas first shows a static preview and does not continuously animate until `開始模擬` is pressed.
- Confirm `開始模擬` starts animation, `暫停模擬` stops it, and switching experiment tabs returns to preview-only mode.
- Confirm controls update KPI previews without starting the continuous animation loop.
- Confirm logout removes `module-experiments.active`.
- Confirm browser console has no errors.
- Confirm no backend API call, DB migration, or worker is introduced by the simulations.

## Follow-up Ideas

- Add downloadable classroom worksheets for each simulation.
- Add preset scenarios such as takeoff, stall recovery, high-viscosity syrup, and crosswind flower hover.
- Add optional low-motion mode that pauses animation by default for accessibility.
