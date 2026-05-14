# Games Mobile Support Verification

Date: 2026-05-14 18:57 Asia/Taipei

## Result

No confirmed mobile-support regressions found.

All 18 registered games expose either visible mobile controls, visible touch/click targets, or numeric/mobile-friendly inputs at a 390x844 touch viewport:

- Chess, Sudoku, Minesweeper, 1A2B
- Tetris, Space Shooter, 3D Shooting Arena
- Open World, Bullet Hell, Stickman Shooter, Real Tetris
- Snake, 2048, Brick Breaker
- Reversi, Go, Gomoku, Chinese Chess

## Evidence

- Static guard: `pytest /home/s92137/hackme_web/tests/frontend/games/test_frontend_games.py`
  - Result: `2 passed`
  - Added coverage: `test_all_games_declare_mobile_controls_or_touch_targets`
- Browser probe: `/tmp/mobile_game_probe.py`
  - Server: `https://127.0.0.1:54273`
  - Viewport: `390x844`, `is_mobile=True`, `has_touch=True`
  - Result artifact: `/tmp/hackme_web_mobile_games_20260514_b/mobile_game_probe.json`
  - Result: `ok=true`, `failures=0`

## Browser Probe Summary

| Game | Mobile target count | Overflow |
| --- | ---: | ---: |
| chess | 8 | 0 |
| sudoku | 4 | 0 |
| minesweeper | 4 | 0 |
| 1a2b | 5 | 0 |
| tetris | 6 | 0 |
| space_shooter | 3 | 0 |
| fps_arena | 10 | 0 |
| open_world | 8 | 0 |
| bullet_hell | 6 | 0 |
| stickman_shooter | 6 | 0 |
| real_tetris | 6 | 0 |
| snake | 4 | 0 |
| game_2048 | 4 | 0 |
| brick_breaker | 3 | 0 |
| reversi | 64 | 0 |
| go | 361 | 0 |
| gomoku | 225 | 0 |
| chinese_chess | 90 | 0 |

## Notes

- Legacy arcade games use explicit `data-game-touch` controls.
- Local arcade modules use the shared `#local-module-game-controls` pointer/touch handler and swipe bridge.
- Chess and board games rely on board-cell buttons/tap targets.
- Sudoku and 1A2B use mobile-friendly inputs; Minesweeper has a mobile flag-mode toggle.
