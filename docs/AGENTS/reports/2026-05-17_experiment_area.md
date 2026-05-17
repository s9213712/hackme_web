# Experiment Area Frontend Module

## Scope

Added a new `experiments` single-page app module for lightweight educational Canvas simulations. The module is intentionally frontend-only: it does not create backend jobs, DB tables, migrations, Flask routes, or background workers.

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

2. Liquid molecules
   - Controls: cup tilt, viscosity, liquid level.
   - Actions: shake cup, pour cup, drop object, reset liquid.
   - KPIs: molecular kinetic energy, visible particle count, object count.

3. Hummingbird hover
   - Controls: wingbeat frequency, wing amplitude, hover stability.
   - Toggle: show estimated control quantities.
   - KPIs: downwash strength, left/right balance, wingbeat cycle.
   - The page lists the posture, visual / vestibular feedback, flower tracking, wing phase / amplitude, lift, wind compensation, muscle delay, energy, and fatigue estimates involved in hover control.

## Important Limitation

These simulations are educational approximations. They are not CFD, SPH, Navier-Stokes, engineering-grade fluid simulation, real aircraft performance calculation, or biological neural-control modeling.

## Verification

Completed checks for this change:

- `node --check public/js/42-experiments.js`
- `python3 -m py_compile server.py routes/public.py`
- `git diff --check`
- Static Playwright smoke without Flask: mounted the Experiment Area DOM/CSS/JS in a headless browser, activated the module, switched all three tabs, and confirmed KPI values updated.

Manual smoke checklist:

- Log in as an allowed account and confirm the sidebar shows `實驗區`.
- Switch all three experiment tabs.
- Confirm each Canvas animates and controls update KPIs.
- Confirm logout removes `module-experiments.active`.
- Confirm browser console has no errors.
- Confirm no backend API call, DB migration, or worker is introduced by the simulations.

## Follow-up Ideas

- Add downloadable classroom worksheets for each simulation.
- Add preset scenarios such as takeoff, stall recovery, high-viscosity syrup, and crosswind flower hover.
- Add optional low-motion mode that pauses animation by default for accessibility.
