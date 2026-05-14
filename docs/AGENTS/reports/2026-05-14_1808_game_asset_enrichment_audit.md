# Game Asset Enrichment Audit

Date: 2026-05-14 18:08 Asia/Taipei

## Status

- Asset files now exist under `public/assets/games/vendor/kenney/`. The curated subset is about 1.5MB / 113 files and keeps each package `LICENSE.txt`.
- `stickman_shooter`: implemented. Uses bundled Kenney New Platformer Pack PNGs for platform tiles, background panels, character/enemy sprites, traps, crates and powerups, with the previous canvas drawings kept as fallback.
- `open_world`: implemented. Uses bundled PNG texture maps for ground, road and supply-crate materials while retaining local Three.js low-poly geometry for vehicles, player, props and buildings.
- `space_shooter`: implemented. Uses bundled Kenney Space Shooter Extension PNGs for player ship, enemy ships, boss ship, lasers, meteors and powerups, with canvas fallback.
- `bullet_hell`: implemented. Uses bundled Particle Pack and Space Shooter Extension PNGs for ship silhouettes, bullets, homing shots, powerups and enemy bullets.
- `brick_breaker`: implemented. Uses bundled Puzzle Pack 2 PNGs for bricks, paddle, ball and hit particles.
- `snake`: implemented. Uses bundled New Platformer Pack PNGs for terrain, water zone, rocks, food, powerup and snake segments.
- `tetris`, `real_tetris`, `minesweeper`, `game_2048`: implemented at the skin layer. Uses bundled Puzzle Pack 2 PNG tile skins through CSS/canvas with existing color/readability fallback.
- Shared game UI: implemented. Buttons, mission badges and achievement badges use bundled Game Icons / UI Pack PNGs while retaining text labels.
- Shared game audio: implemented. User-triggered button clicks, success/error notices and selected gameplay events use bundled low-volume OGG sounds from Interface Sounds / Impact Sounds.

## Source Packs Checked

All checked source packs list `Creative Commons CC0` on Kenney:

- Kenney New Platformer Pack: https://kenney.nl/assets/new-platformer-pack
- Kenney Space Shooter Extension: https://kenney.nl/assets/space-shooter-extension
- Kenney Particle Pack: https://kenney.nl/assets/particle-pack
- Kenney Puzzle Pack 2: https://kenney.nl/assets/puzzle-pack-2
- Kenney Game Icons: https://kenney.nl/assets/game-icons
- Kenney Interface Sounds: https://kenney.nl/assets/interface-sounds
- Kenney Impact Sounds: https://kenney.nl/assets/impact-sounds
- Kenney Graveyard Kit: https://kenney.nl/assets/graveyard-kit
- Kenney Blaster Kit: https://kenney.nl/assets/blaster-kit
- Kenney Blocky Characters: https://kenney.nl/assets/blocky-characters
- Kenney Space Kit: https://kenney.nl/assets/space-kit
- Kenney Space Shooter Redux: https://kenney.nl/assets/space-shooter-redux
- Kenney Board Game Pack / Playing Cards Pack: https://kenney.nl/assets/boardgame-pack, https://kenney.nl/assets/playing-cards-pack
- Kenney UI Pack / UI Pack Sci-Fi: https://kenney.nl/assets/ui-pack, https://kenney.nl/assets/ui-pack-sci-fi
- Kenney Nature Kit: https://kenney.nl/assets/nature-kit

## Additional Reuse Candidates

- `fps_arena`: still the best place for the next visual jump. It should use optimized model assets or a shared primitive-model helper instead of only PNG textures.
- `open_world`: if the project accepts model loader work later, add GLTF/GLB loading for vehicles/characters. Current pass deliberately limits 3D changes to safe texture maps.
- `go`, `gomoku`, `reversi`, `chess`, `chinese_chess`: use Board Game Pack / Playing Cards Pack only as subtle board/piece polish. Avoid replacing core board readability.
- Non-game pages: avoid decorative asset use on trading/admin/storage pages. The only good fit is a restrained UI Pack influence for game cards, achievements, missions and empty states, because operational pages should stay dense and utilitarian.

## Recommendation

Keep using curated subsets, not whole downloaded packs. The current checked-in assets are small enough to be reasonable, have package license files, and are served from the app so games remain offline-friendly after the first page load.
