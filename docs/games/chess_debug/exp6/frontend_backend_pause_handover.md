# Exp6 Frontend/Backend Pause Handover

Date: 2026-05-18

Development is paused. Exp6 is wired as a selectable chess practice engine, but
no candidate is promoted and no training branch is active.

## Runtime Lock

- Champion path: `runtime/games/models/chess_experiment_6_neural.npz`
- Expected md5: `1c27627adb3c4597561bc7509438e25c`
- Expected mode: `444`
- Champion modified during this pause pass: false

## Repo Data Cleanup

Raw runtime, test, and training data were moved out of the repo during the
pause cleanup.

Archive root on this machine:

```text
/tmp/hackme_web_repo_data_archive_20260518
```

Moved data includes:

- `runtime/private/games/exp6` JSON/JSONL/TXT datasets and downloaded PGN/ZIP
  sources.
- `runtime/reports`.
- old runtime Exp6 model snapshots, excluding the locked champion and lock
  file.
- `docs/games/evidence`.
- raw `.json` / `.jsonl` files from `docs/games/archive/chess_debug`.
- Python/test cache directories.

Kept in repo:

- scripts under `scripts/`.
- narrative debug docs under `docs/games/chess_debug/exp6`.
- markdown archive history under `docs/games/archive/chess_debug`.
- current runtime champion and `CHAMPION_LOCK.md`.

## Frontend/Backend Wiring

The active user-facing path is:

1. `public/index.html`
   - Static chess practice select includes `experiment 6:neuralnet`.
   - Root chess candidate select also lists Exp6 for visibility.
2. `public/js/games/chess.js`
   - `renderChessPracticeDifficultyOptions()` consumes `/api/games/catalog`.
   - `createChessPracticeMatch()` posts selected difficulty to
     `/api/games/chess/practice`.
   - `gameDifficultyLabel()` displays `experiment 6:neuralnet` as
     `Exp6 Neural Network`.
3. `routes/games.py`
   - `/api/games/catalog` returns Exp6 from `computer_difficulty_options()`.
   - `normalize_computer_difficulty()` accepts `experiment 6:neuralnet`.
   - `/api/games/chess/practice` persists the selected difficulty.
   - `choose_computer_move()` dispatches Exp6 to
     `services.games.chess_exp6.choose_experiment_neural_move()`.
4. `bootstrap.schema.sql`
   - Fresh installs now allow `experiment 0:minimax2ply`,
     `experiment 1:search`, and `experiment 6:neuralnet` in
     `game_matches.computer_difficulty`, matching runtime schema.

## Verification

Focused contract tests should cover:

- `/api/games/catalog` includes Exp0 through Exp6, Stockfish only when locally
  available.
- `/api/games/chess/practice` accepts Exp6 and records a computer reply for
  both human-white and human-black practice starts.
- Frontend assets include Exp6 static fallback labels and dynamic catalog
  rendering hooks.

Recommended command:

```bash
python3 -m pytest \
  tests/games/test_games.py::test_game_matches_difficulty_enum_in_sync_across_bootstrap_and_runtime \
  tests/games/test_games.py::test_game_catalog_includes_solo_games \
  tests/games/test_games.py::test_game_catalog_adds_stockfish_only_when_local_binary_available \
  tests/games/test_games.py::test_chess_practice_difficulty_is_persisted_and_rejects_invalid_value \
  tests/frontend/games/test_frontend_games.py::test_game_zone_frontend_assets_are_wired \
  -q
```

## Restart Notes

Do not restart with policy-rerank. Current evidence says Exp6 needs stronger
value/search consequence judgement, not root move guessing.

Next acceptable branch:

- value-only evaluator v2
- generic curriculum / Stockfish-labelled train/dev/heldout split
- no staged FEN or move leakage into docs or training answers
- deterministic sanity before staged early gate
- staged gates only via `chess_exp6_curriculum.play_staged_test()`
