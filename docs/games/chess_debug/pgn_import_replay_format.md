# PGN import for chess replay training

Use `scripts/games/chess_pgn_to_replay.py` when you want external PGN games to feed the same replay JSONL format used by `chess_replay_prepare.py`.

Default output is:

```bash
~/chess_results/chess_replays_imported.jsonl
```

That default is deliberate. Review imported data first, then point `--output-jsonl` at a runtime replay buffer only when you are ready:

```bash
python3 scripts/games/chess_pgn_to_replay.py \
  --input-pgn ~/Downloads/master_games.pgn \
  --output-jsonl runtime/reports/games/chess_replays.jsonl \
  --min-elo 2200 \
  --sample-size 100 \
  --seed 20260511
```

## Download and sample

The script can download a direct PGN URL before converting it:

```bash
python3 scripts/games/chess_pgn_to_replay.py \
  --source-url https://example.com/games.pgn.gz \
  --min-elo 2200 \
  --sample-size 50 \
  --seed 42
```

## Interactive mode

Use interactive mode when selecting a source manually:

```bash
python3 scripts/games/chess_pgn_to_replay.py --interactive
```

It prompts for:

- source: local file or download URL
- classification/filter preset: master decisive, elite, strong rapid/classical, endgame material, special rules, or custom tag
- game count, scan limit, seed, and minimum ply count
- position scope: any, complete games from the standard start, or FEN fragments
- output format: replay JSONL only, or replay JSONL plus prepared train/eval dataset
- optional distill manifest for a later teacher-distill run
- output directory and filename

The script prints progress to stderr and the final machine-readable JSON summary to stdout. By default, if filters match no games, it returns a non-zero exit code and writes an explicit `errors` entry instead of silently creating an empty success report.

For non-interactive automation, the same controls are available through flags:

```bash
python3 scripts/games/chess_pgn_to_replay.py \
  --input-pgn ~/Downloads/games.pgn \
  --output-format prepared-dataset \
  --output-jsonl ~/chess_results/master_replays.jsonl \
  --prepared-output-dir ~/chess_results/master_dataset \
  --min-elo 2200 \
  --result decisive \
  --require-tag contains_castling \
  --position-scope complete \
  --sample-size 100 \
  --seed 20260511 \
  --distill-manifest ~/chess_results/master_replays.distill_manifest.json
```

Supported input/download formats:

- `.pgn`
- `.zip` archives that contain a `.pgn`
- `.pgn.gz`
- `.pgn.bz2`
- `.pgn.zst` if the optional Python package `zstandard` is installed

`--sample-size` uses deterministic reservoir sampling. The same input and `--seed` produce the same selected game set.

## Labels

Imported records include labels under `pgn_labels` and `training_tags`. Current labels include:

- rating band: `elite`, `master`, `strong_club`, `club`, `low_or_unknown_quality`
- time control class: `bullet`, `blitz`, `rapid`, `classical`, `unknown_time_control`
- length bucket: `short_game`, `medium_game`, `long_game`
- material bucket: `full_material`, `reduced_material`, `endgame_material`
- special rules: `castling`, `promotion`, `en_passant`
- tactical/result hints: `contains_capture`, `contains_check`, `checkmate`, `short_decisive`, `decisive`, `draw_or_unknown`

These are lightweight labels for filtering and analysis. They are not a replacement for deterministic strength gates or teacher-reviewed labels.

## Recommended sources

Good inputs are curated master games or high-rated games. Avoid blindly importing low-rated blitz/bullet games into trusted data.

Useful sources:

- Lichess open database: `https://database.lichess.org/`
- Lichess broadcast database: `https://database.lichess.org/#broadcasts`
- The Week in Chess PGN archive: `https://theweekinchess.com/twic`
- PGN Mentor game files: `https://www.pgnmentor.com/files.html`

Recommended filters:

```bash
--min-elo 2200 --min-ply 12 --result decisive
```

For a small random batch:

```bash
python3 scripts/games/chess_pgn_to_replay.py \
  --input-pgn ~/Downloads/games.pgn \
  --sample-size 20 \
  --seed 20260511
```

For all eligible games:

```bash
python3 scripts/games/chess_pgn_to_replay.py \
  --input-pgn ~/Downloads/games.pgn \
  --max-games 0
```
