# ComfyUI / Games / Experiments Optimization

Date: 2026-05-28

## Scope

- ComfyUI and Hugging Face Diffusers control-plane requests.
- Games page score submission, leaderboards, invites, and chess match list hot
  paths.
- Browser-only Experiments page rendering cost.

## Changes

- Added short server-side Hugging Face repo metadata caching for Diffusers
  inspection, keyed by repo, mode, and token fingerprint.
- Added frontend request de-duplication and short cache windows for Diffusers
  repo inspection and ComfyUI model-list loads. Manual refresh, local startup,
  model download, and model upload force a fresh model-list read.
- Changed game score submits from the frontend to
  `/api/games/{game_key}/solo-scores?compact=1`, so score recording no longer
  rebuilds the leaderboard before the frontend's explicit leaderboard refresh.
- Added game indexes for chess leaderboard weeks, visible match lists, invites,
  multiplayer invites, and solo best-time / best-score ranking queries.
- Made the Experiments page choose lower particle counts and lower DPR caps on
  low-core or reduced-motion clients, and clamped large animation frame gaps
  after tab suspension.

## Verification

- `python3 -m py_compile routes/games.py services/comfyui/huggingface.py tests/comfyui/test_diffusers_client.py tests/games/test_games.py tests/frontend/comfyui/test_comfyui_diffusers_repo_ui.py tests/frontend/games/test_frontend_games.py tests/frontend/test_experiments_performance.py`
- `pytest -q tests/comfyui/test_diffusers_client.py tests/frontend/comfyui/test_comfyui_diffusers_repo_ui.py tests/frontend/comfyui/test_comfyui_idle_retry.py tests/frontend/test_experiments_performance.py`
- `pytest -q tests/games/test_games.py -k "solo or schema_migrates or leaderboard"`
- `pytest -q tests/frontend/games/test_frontend_games.py`
- `pytest -q tests/comfyui/test_diffusers_client.py tests/comfyui/test_comfyui_settings_defaults.py tests/comfyui/settings/test_comfyui_settings.py tests/comfyui/test_template_safety.py tests/comfyui/test_template_import_endpoint.py tests/comfyui/test_execution_generate_image.py tests/comfyui/generation/test_comfyui_generation.py`
- `pytest -q tests/frontend/comfyui/test_comfyui_diffusers_repo_ui.py tests/frontend/comfyui/test_comfyui_idle_retry.py tests/frontend/comfyui/test_comfyui_history_ui.py tests/frontend/comfyui/test_comfyui_workflow_template_ui.py tests/frontend/test_experiments_performance.py`
- `pytest -q tests/games/test_games.py tests/games/test_board_ai.py tests/games/test_board_arena.py tests/games/test_chess_opening_book.py`
- `pytest -q tests/frontend/games/test_frontend_games.py tests/scripts/games/test_chess_pipeline_dryrun.py tests/scripts/games/test_chess_pipeline_report.py`

All listed checks passed.

## Next Optimization Queue

- Add live microbenchmarks for `/api/comfyui/models`,
  `/api/comfyui/diffusers/inspect`, and game leaderboard endpoints.
- Move heavy root chess engine dashboard reads to a short snapshot if it starts
  combining filesystem, model registry, and training pipeline state in one
  request.
- Add an isolated browser performance probe for the Experiments page on a small
  viewport with reduced-motion enabled.
