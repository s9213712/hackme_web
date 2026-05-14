# chess_self_play_train

- generated_at: `2026-05-14T05:10:57.165262Z`
- games_played: `0`
- experiment_db_path: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp3_exp4_big_retrain_2026-05-14_retry1/_runtime/exp3/games/models/chess_experiment.db`
- experiment_2_nn_model_path: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp3_exp4_big_retrain_2026-05-14_retry1/_runtime/exp3/games/models/chess_experiment_2_nn.json`
- experiment_3_dl_model_path: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp3_exp4_big_retrain_2026-05-14_retry1/_runtime/exp3/games/models/candidates/runs/pipeline_20260514T045848Z/chess_experiment_3_dl.json`
- experiment_4_pv_model_path: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp3_exp4_big_retrain_2026-05-14_retry1/_runtime/exp3/games/models/candidates/runs/pipeline_20260514T045848Z/chess_experiment_4_pv.json`
- experiment_5_nnue_model_path: `/home/s92137/hackme_web/docs/games/evidence/stockfish_teacher/exp3_exp4_big_retrain_2026-05-14_retry1/_runtime/exp3/games/models/candidates/runs/pipeline_20260514T045848Z/chess_experiment_5_nnue_experience.json`

## Results

- white_wins: `0`
- black_wins: `0`
- draws: `0`

## Updates

- experiment: `0`
- experiment 2:nn: `0`
- experiment 3:dl: `0`
- experiment 4:pv: `0`
- experiment 5:nnue: `0`
- teacher_guidance_exp1: `0`
- teacher_guidance_exp2: `0`
- teacher_guidance_exp3: `0`
- teacher_guidance_exp4: `0`
- teacher_guidance_exp5: `0`
- teacher_distillation_exp3: `0`

## Requested Games

- teacher_vs_exp1: `0`
- teacher_vs_exp2: `0`
- teacher_vs_exp3: `0`
- teacher_vs_exp4: `0`
- hard_vs_exp1: `0`
- hard_vs_exp2: `0`
- hard_vs_exp3: `0`
- hard_vs_exp4: `0`
- cross_play: `0`
- cross_exp1_exp3: `0`
- cross_exp2_exp3: `0`
- cross_exp1_exp4: `0`
- cross_exp2_exp4: `0`
- cross_exp3_exp4: `0`

## Recent Matches


## Post-Training Smoke

- pass: `True`
- games_played: `20`
- suspicious_matches: `0`

### Smoke Standings

- teacher: `W=0` `L=1` `D=9` `score=4.5` `win_rate=0.0`
- hard: `W=1` `L=4` `D=5` `score=3.5` `win_rate=0.1`
- experiment 3:dl: `W=2` `L=0` `D=2` `score=3.0` `win_rate=0.5`
- experiment 5:nnue: `W=2` `L=0` `D=2` `score=3.0` `win_rate=0.5`
- experiment: `W=1` `L=1` `D=2` `score=2.0` `win_rate=0.25`
- experiment 2:nn: `W=0` `L=0` `D=4` `score=2.0` `win_rate=0.0`
- experiment 4:pv: `W=0` `L=0` `D=4` `score=2.0` `win_rate=0.0`

## Round-Robin Benchmark

- rounds: `1`
- games_played: `42`
- suspicious_matches: `0`
- opening_split: `eval`

### Benchmark Standings

- experiment 5:nnue: `W=10` `L=0` `D=2` `score=11.0` `score_rate=0.9167`
- experiment 3:dl: `W=4` `L=2` `D=6` `score=7.0` `score_rate=0.5833`
- experiment 2:nn: `W=1` `L=2` `D=9` `score=5.5` `score_rate=0.4583`
- experiment 4:pv: `W=0` `L=1` `D=11` `score=5.5` `score_rate=0.4583`
- hard: `W=1` `L=4` `D=7` `score=4.5` `score_rate=0.375`
- experiment: `W=0` `L=3` `D=9` `score=4.5` `score_rate=0.375`
- teacher: `W=0` `L=4` `D=8` `score=4.0` `score_rate=0.3333`

### Benchmark Elo

- experiment 5:nnue: `elo=1597.55` `games=12`
- experiment 3:dl: `elo=1517.37` `games=12`
- experiment 4:pv: `elo=1495.37` `games=12`
- experiment 2:nn: `elo=1491.61` `games=12`
- experiment: `elo=1473.17` `games=12`
- hard: `elo=1467.06` `games=12`
- teacher: `elo=1457.87` `games=12`

### Human Probe Suite

- cases: `10`
- pass: `False`

- experiment 2:nn: `passed=8` `failed=2` `score_rate=0.8`
- experiment 5:nnue: `passed=8` `failed=2` `score_rate=0.8`
- experiment 3:dl: `passed=7` `failed=3` `score_rate=0.7`
- hard: `passed=6` `failed=4` `score_rate=0.6`
- experiment 4:pv: `passed=3` `failed=7` `score_rate=0.3`
- experiment: `passed=2` `failed=8` `score_rate=0.2`
- teacher: `passed=2` `failed=8` `score_rate=0.2`

### Endgame Suite

- cases: `6`
- pass: `False`

- experiment 2:nn: `passed=6` `failed=0` `score_rate=1.0`
- experiment 3:dl: `passed=6` `failed=0` `score_rate=1.0`
- experiment 5:nnue: `passed=6` `failed=0` `score_rate=1.0`
- experiment 4:pv: `passed=5` `failed=1` `score_rate=0.8333`
- hard: `passed=5` `failed=1` `score_rate=0.8333`
- teacher: `passed=5` `failed=1` `score_rate=0.8333`
- experiment: `passed=3` `failed=3` `score_rate=0.5`
