# 2026-05-13 Exp5 殘局轉換補強紀錄

## 目標

使用者要求繼續修 `experiment 5:nnue`，解決先前指出的問題，並讓棋力估計至少再進一階。前一版 exp5 已能避免明顯輸棋，但完整 reviewer 五局仍是 `0W/5D/0L`，全部三次重複，代表它偏向守和，勝勢轉換能力不足。

本次補強的目標不是堆高固定題分數，而是改善完整局中「領先時如何避免 perpetual check / threefold repetition，並把優勢轉成將死或可持續推進」。

## 修改內容

- `services/games/chess_nnue.py`
  - 新增殘局轉換評估 `_endgame_conversion_score()`。
  - 在低子力或 20 手後，且某方至少領先約 `500cp` 時啟用。
  - 獎勵領先方國王從邊角走向中心。
  - 獎勵領先方通路兵推進。
  - 新增王步 move-order bonus，讓領先方在殘局受將時更願意脫離邊線循環。
  - 新增 `_conversion_check_evasion_filter()`：只在「受將、明顯領先、候選步為王步」時啟用，避免 alpha-beta 因短視評估選回容易 perpetual 的邊角王步。
- `scripts/games/game_ai_strength_eval.py`
  - exp5 若達到 `total >= 39.5`、固定題 `100%`、sparring `100%`，棋力估計從 `Elo 1200-1500` 進階為 `Elo 1500-1800；非高階引擎`。
  - 這是粗略應用內換算，不是外部 Elo 標定。
- `tests/games/test_chess_exp5_architecture.py`
  - 新增兩個殘局受將轉換測試，重現先前 reviewer game 的 perpetual-check 弱點。
  - 驗證 exp5 在領先的 rook/endgame 局面中選擇 `Kc3`、`Kb3` 這類主動王步，而不是回到邊角循環。

## 驗證結果

| 驗證項 | 結果 |
|---|---:|
| exp5 architecture / opening / practice 目標測試 | `30 passed` |
| 語法檢查 | pass |
| exp5 分數探針 | `40.00/40` |
| exp5 固定題 | `14.40/14.40` |
| exp5 AI-vs-random sparring | `6W/0D/0L` |
| exp5 100 題 holdout | `100/100` |
| downloaded PGN human probes | `40/40` |
| exp5 完整 reviewer 五局 | `2W/3D/0L` |
| 隔離伺服器 live smoke | pass；board AI `9/9`，chess practice `12/12` |

主要產物：

- `docs/games/2026-05-13_exp5_score_probe_conversion.json`
- `docs/games/2026-05-13_exp5_holdout_100_probe_conversion.json`
- `docs/games/2026-05-13_exp5_conversion_regression.json`
- `docs/games/2026-05-13_exp5_strong_before_next_fix.json`
- `docs/games/2026-05-13_exp5_conversion_live_smoke.json`

## 前後比較

| 指標 | 前一版 | 本次修後 |
|---|---:|---:|
| 分數探針 | `39.89/40` | `40.00/40` |
| 固定題 | `14.40/14.40` | `14.40/14.40` |
| 100 題 holdout | `100/100` | `100/100` |
| AI-vs-random sparring | `5W/1D/0L` | `6W/0D/0L` |
| 完整 reviewer 五局 | `0W/5D/0L` | `2W/3D/0L` |
| 完整 reviewer 結束原因 | 全部三次重複 | 2 局將死、3 局三次重複 |
| 約略棋力 | `Elo 1200-1500` | `Elo 1500-1800；非高階引擎` |

## 解讀

這次是實質提升：完整局從只能守和，提升到能在同一 reviewer policy 下將死兩局；固定題與 100 題 holdout 沒有回退。因此可以把 exp5 的應用內估計往上調一階。

仍需保守解讀：

- 這不是 FIDE/USCF Elo 實測，只是根據固定題、sparring、holdout 和完整 reviewer games 的粗略區間。
- exp5 還不是高階引擎。剩下三局是 exp5 在劣勢或被壓制局面中守成三次重複，這對結果合理，但也說明它還缺少真正高階的全局壓制、長線殘局技術與反 perpetual planning。
- 下一階若要挑戰 `Elo 1800+`，需要加入更完整的 search extension、perpetual-check detection、rook ending tablebase-like heuristics、king shelter 重建，以及更強對手基線，而不是再只加局部固定題。
